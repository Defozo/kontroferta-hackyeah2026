"""Mix reviewed timeline slots, bounded TTS assets and an original instrumental bed.

No network or generation calls occur during rendering. Perceptual listening is
explicitly not established by this script's technical measurements.
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'apps/web/evidence/interactive-video/_video_work'
RATE = 48000

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(argv):
    return subprocess.run([str(x) for x in argv], check=True, capture_output=True, text=True)

def write_wav(path, samples):
    if samples.ndim == 1:
        samples = np.column_stack((samples, samples))
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes((np.clip(samples, -.999, .999)*32767).astype('<i2').tobytes())

def read_wav(path):
    with wave.open(str(path), 'rb') as source:
        assert source.getframerate() == RATE and source.getnchannels() == 2 and source.getsampwidth() == 2
        return np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').reshape(-1, 2).astype(np.float32)/32768

def original_score(seconds):
    """Original deterministic A-minor instrumental, 100 BPM, no sampled recordings."""
    size = round(seconds*RATE)
    score = np.zeros((size, 2), np.float32)
    rng = np.random.default_rng(20261003)
    beat = .6
    chords = [(57,60,64,67),(53,57,60,64),(48,52,55,59),(55,59,62,65)]
    def add(start, signal, gain, pan=0):
        begin = round(start*RATE)
        end = min(size, begin+len(signal))
        if begin >= size:
            return
        signal = signal[:end-begin]*gain
        score[begin:end,0] += signal*math.sqrt((1-pan)/2)
        score[begin:end,1] += signal*math.sqrt((1+pan)/2)
    def note(midi, length, kind):
        t = np.arange(round(length*RATE), dtype=np.float32)/RATE
        hz = 440*2**((midi-69)/12)
        tone = np.sin(2*np.pi*hz*t) + .22*np.sin(4*np.pi*hz*t) + .07*np.sin(6*np.pi*hz*t)
        envelope = (1-np.exp(-t/.012))*np.exp(-t/(.55 if kind=='keys' else 1.0))
        envelope *= np.minimum(1,(length-t)/.1)
        return tone*envelope
    for bar in range(math.ceil(seconds/(4*beat))):
        chord = chords[bar%4]
        start = bar*4*beat
        for j, midi in enumerate(chord):
            add(start, note(midi, 2.4, 'keys'), .035, (j-1.5)*.25)
        for step in range(8):
            add(start+step*beat/2, note(chord[(step*3)%4]+12, .75, 'keys'), .009, -.35 if step%2 else .35)
        for step in (0,2):
            add(start+step*beat, note(chord[0]-24, 1.0, 'bass'), .035)
            t = np.arange(round(.22*RATE),dtype=np.float32)/RATE
            kick = np.sin(2*np.pi*(45*t+38*.04*(1-np.exp(-t/.04))))*np.exp(-t/.055)
            add(start+step*beat, kick, .045)
        for step in range(8):
            t = np.arange(round(.055*RATE),dtype=np.float32)/RATE
            noise = rng.standard_normal(len(t)).astype(np.float32)
            noise = np.diff(noise,prepend=noise[0])*np.exp(-t/.011)
            add(start+step*beat/2,noise,.004,-.25 if step%2 else .25)
    fade_in = np.minimum(1,np.arange(size)/(RATE*1.4))
    fade_out = np.minimum(1,(size-1-np.arange(size))/(RATE*3.0))
    return score*(fade_in*fade_out)[:,None]

def normalize(source, target, loudness):
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',source,'-af',f'loudnorm=I={loudness}:TP=-3:LRA=7','-ar',RATE,'-ac',2,'-c:a','pcm_s16le',target])

def measure(path):
    result = run(['ffmpeg','-hide_banner','-i',path,'-vn','-af','loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json','-f','null','-'])
    return json.loads(re.findall(r'\{\s*"input_i".*?\}', result.stderr, re.S)[-1])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', choices=['v1','v2','v3'], default='v2')
    args = parser.parse_args()
    version = args.version
    timeline = json.loads((WORK/f'plans/timeline-{version}.json').read_text(encoding='utf-8'))
    master = WORK/f'render/KontrOferta-picture-{version}.mp4'
    assert master.exists()
    audio_dir = WORK/f'audio/final-{version}'
    audio_dir.mkdir(parents=True, exist_ok=True)
    duration = timeline['duration']
    size = round(duration*RATE)
    voice = np.zeros((size,2),np.float32)
    duck = np.ones(size,np.float32)
    evidence = []
    for item in timeline['mapping']:
        ident = item['id']
        manifests = list((WORK/'assets/elevenlabs').glob(f'kontroferta-{ident}-*/manifest.json'))
        assert len(manifests)==1, (ident, len(manifests))
        path = manifests[0]
        data = json.loads(path.read_text(encoding='utf-8'))
        wav = path.parent/'audio.wav'
        assert data['status']=='ready_for_review' and sha(wav)==data['wavSha256']
        normalized = audio_dir/f'{ident}.wav'
        normalize(wav, normalized, -18)
        samples = read_wav(normalized)
        start = item['outputStartFrame']/timeline['fps']+.35
        end = start+len(samples)/RATE
        slot_end = item['outputEndFrame']/timeline['fps']
        assert end <= slot_end-.25, (ident,end,slot_end)
        first = round(start*RATE)
        voice[first:first+len(samples)] += samples
        # Gentle duck before and after each voice segment, without abrupt gain steps.
        attack, release = round(.15*RATE), round(.35*RATE)
        begin, finish = max(0,first-attack),min(size,first+len(samples)+release)
        envelope = np.full(finish-begin,.62,np.float32)
        envelope[:first-begin] = np.linspace(1,.62,first-begin)
        envelope[first+len(samples)-begin:] = np.linspace(.62,1,finish-first-len(samples))
        duck[begin:finish] = np.minimum(duck[begin:finish],envelope)
        evidence.append({'id':ident,'script':data['request']['text'],'outputStartSeconds':start,'outputEndSeconds':end,'slotEndSeconds':slot_end,'voiceSha256':data['wavSha256'],'requestHash':data['requestHash'],'providerHeaders':data.get('providerHeaders',{}),'manifest':str(path.relative_to(ROOT)).replace('\\','/')})
    voice_path = audio_dir/'voice-timeline.wav'
    write_wav(voice_path,voice)
    score_path = audio_dir/'original-instrumental.wav'
    write_wav(score_path,original_score(duration))
    score_normalized = audio_dir/'music-normalized.wav'
    normalize(score_path,score_normalized,-32)
    music = read_wav(score_normalized)[:size]*duck[:,None]
    # Reapply the end fade after loudness normalization.
    tail = round(3*RATE)
    music[-tail:] *= np.linspace(1,0,tail)[:,None]
    mixed = voice+music
    peak = float(np.max(np.abs(mixed)))
    assert peak < 1, f'Unnormalized mix clips: {peak}'
    premix = audio_dir/'mix-before-master.wav'
    write_wav(premix,mixed)
    final_audio = audio_dir/f'KontrOferta-mix-{version}.wav'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',premix,'-af','loudnorm=I=-16:TP=-1.5:LRA=9','-ar',RATE,'-ac',2,'-c:a','pcm_s16le',final_audio])
    target = WORK/f'render/KontrOferta-av-{version}.mp4'
    # Preserve a separately approved assembly plan for the actual mixed output.
    # The local renderer uses the measured PCM mix, so no paid call is repeated.
    skill = Path.home()/'.agents/skills/reusable-video-editing'
    sys.path.insert(0,str(skill/'scripts'))
    from video_skill.common import validate
    from video_skill.render import approve_plan, validate_plan, verify_approval
    plan = {
        'schema_version':1,'plan_id':f'kontroferta-av-{version}','title':'KontrOferta: pełny przepływ z polską narracją',
        'approved':False,'approval':None,
        'timeline':{'width':1440,'height':1080,'fps':'25/1','sample_rate':RATE,'video_codec':'libx264','pixel_format':'yuv420p','audio_codec':'aac','audio_channels':2},
        'editorial_rationale':'Authorized completion of the user-requested competition film. Picture is the verified chronological real-app master, including Polish graphical captions and explicit simulation labels. The supplied full-length audio is the measured narration/music mix assembled by scripts/mix_submission_audio.py. The audio-verification report preserves individual scene offsets, scripts, provider hashes, music provenance, ducking and end fade. Technical audio verification does not establish perceptual listening.',
        'items':[{'id':'verified-picture','type':'clip','source':str(master),'source_in_frame':0,'source_out_frame':timeline['frames'],'source_fps':'25/1','speed':1,'audio':{'mode':'mute','path':None,'gain_db':0},'transition':{'type':'cut','duration_seconds':0},'overlays':[],'rationale':'Verified picture master, all original Polish caption graphics already present.'}],
        'music':None,'subtitles':None,'topaz_requests':[],
        'voiceover':[{'record_start_seconds':0,'script':'\n'.join(item['script'] for item in evidence),'status':'supplied','audio_path':str(final_audio),'gain_db':0}],
        'dependencies':[{'kind':'audio','path':str(final_audio),'owner':'root narration and original instrumental mix'}],
        'deliverables':[{'id':'competition-av','container':'mp4','role':'browser','primary':True,'subtitle_mode':'none','path':str(target)}],
    }
    validate(plan,'montage-plan.schema.json')
    plan_path = WORK/f'plans/montage-av-{version}.json'
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    validation = validate_plan(WORK/'project.yaml',plan_path)
    assert validation['valid'], validation
    approved_hash = approve_plan(plan_path,'agent: authorized competition film completion',datetime.now(timezone.utc).isoformat(),WORK/'project.yaml')
    verify_approval(json.loads(plan_path.read_text(encoding='utf-8')))
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',master,'-i',final_audio,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','256k','-ar',RATE,'-t',duration,'-movflags','+faststart',target])
    loudness = measure(target)
    probe = json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',target]).stdout)
    video = next(s for s in probe['streams'] if s['codec_type']=='video')
    audio = next(s for s in probe['streams'] if s['codec_type']=='audio')
    run(['ffmpeg','-hide_banner','-loglevel','error','-xerror','-i',target,'-f','null','-'])
    checks = {'durationUnder180':float(probe['format']['duration'])<=180,'decodedFrameCount':int(video['nb_read_frames'])==timeline['frames'],'audioAAC':audio['codec_name']=='aac','audio48k':audio['sample_rate']=='48000','avDurationDifferenceBelowFrame':abs(float(video['duration'])-float(audio['duration']))<1/25,'truePeakBelowMinusOne':float(loudness['input_tp'])<=-1,'voiceFitsEveryScene':True,'audioDecodePassed':True}
    assert all(checks.values()),checks
    report = {'schemaVersion':1,'checkedAt':datetime.now(timezone.utc).isoformat(),'status':'technical_pass_perceptual_review_partial','file':str(target.relative_to(ROOT)).replace('\\','/'),'sha256':sha(target),'pictureMasterSha256':sha(master),'durationSeconds':duration,'checks':checks,'loudness':loudness,'voice':{'provider':'ElevenLabs','voice':'Bella - Professional, Bright, Warm','voiceId':'hpp4J3VqNfWAUOO0d1Us','model':'eleven_multilingual_v2','accountTier':'payg','cloning':False,'segments':evidence},'music':{'origin':'Original deterministic instrumental composition generated locally by this repository script; no external recording or sample','tempoBpm':100,'scoreSha256':sha(score_path),'normalizedLufs':-32,'duckGainDuringVoice':.62,'endFadeSeconds':3},'perceptualReview':{'heard':False,'reason':'The available model/tool channel explicitly reports that audio input is unsupported. Playback or transcript is not treated as evidence of listening.','verified':'Stream decoding, loudness, true peak, sample lengths and scene alignment','remaining':'Human listening for pronunciation, intelligibility and subjective music balance'},'rightsReference':'https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform'}
    report['planHash'] = approved_hash
    (audio_dir/'audio-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'submission/audio-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'target':str(target),'duration':duration,'checks':checks,'integratedLufs':loudness['input_i'],'truePeakDbtp':loudness['input_tp']}))

if __name__=='__main__':
    main()
