import type { Analysis, CaseDetail } from './types';

/** Exact arithmetic for the authored public A/B/C example only, no AI or private data. */
export function previewRecordedDemo(data:CaseDetail, surcharge:number):Analysis {
  if(!Number.isSafeInteger(surcharge)||surcharge<0||surcharge>10000000)throw new Error('Dopłata musi wynosić od 0 do 100000 PLN. / Surcharge must be between 0 and 100000 PLN.');
  if(!data.recordedDemo||data.offers.map(o=>o.id).sort().join(',')!=='A,B,C')throw new Error('Nieobsługiwany zapis przykładu. / Unsupported recorded example.');
  const costs={A:480000+surcharge,B:550000,C:510000};
  const feasible=costs.A<=560000?['A','B']:['B'];
  const winners=costs.A<costs.B?['A']:costs.A===costs.B?['A','B']:['B'];
  const source=data.analysis!;
  return {...source,status:winners.length===1?'unique_winner':'common_winner',complete:true,scenario_count:1,unique_winner:winners.length===1?winners[0]:undefined,common_winners:winners,robust_feasible:feasible,questions:[],witnesses:[],issues:[],offers:source.offers.map(o=>({...o,min_cost_minor:costs[o.id as keyof typeof costs],max_cost_minor:costs[o.id as keyof typeof costs],always_feasible:feasible.includes(o.id),sometimes_feasible:feasible.includes(o.id),possible_winner:winners.includes(o.id),common_winner:winners.includes(o.id)})),scenarios:[{id:'recorded-preview',assignment:{technician_surcharge:surcharge},costs,feasible,winners,exclusions:{A:costs.A>560000?[{code:'budget',message:'Przekroczony budżet / Over budget'}]:[],B:[],C:[{code:'ready_by',message:'Gotowość 09:30, wymagane 09:00 / Ready 09:30, required 09:00'}]},breakdown:{}}],preview:true,recordedDemo:true};
}

export async function recordedRequest(path:string,options:RequestInit):Promise<unknown>{
  if(options.method&&options.method!=='GET')throw new Error('Publiczny przykład jest tylko do odczytu. / Public example is read-only.');
  const response=await fetch('/demo-data.json',{cache:'no-cache'});
  if(!response.ok)throw new Error('Nie udało się wczytać zapisanego przykładu. / Could not load the recorded example.');
  const data=await response.json() as CaseDetail;
  if(path==='/demo')return data;
  if(path.startsWith('/demo/recalculate?')){const query=new URLSearchParams(path.split('?')[1]);if(query.get('variable')!=='technician_surcharge')throw new Error('Nieznana zmienna przykładu. / Unknown example variable.');return previewRecordedDemo(data,Number(query.get('value')));}
  throw new Error('Ta operacja wymaga pełnej aplikacji z logowaniem. / This operation requires the full signed-in application.');
}
