/** Convert explicitly chosen local date/time to a unique instant, including DST. */
export function zonedInstant(date: string, time: string, timezone: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time)) throw new Error('Podaj pełną datę i godzinę. / Enter a complete date and time.');
  const formatter = new Intl.DateTimeFormat('en-CA', {timeZone: timezone, year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
  const local = (instant:number) => {
    const parts = Object.fromEntries(formatter.formatToParts(instant).map(p=>[p.type,p.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  };
  const requested=`${date}T${time}`;
  const nominal=Date.parse(`${requested}:00Z`);
  const offsets=new Set<number>();
  for(let hours=-36;hours<=36;hours+=6){const instant=nominal+hours*3600000;offsets.add(Date.parse(`${local(instant)}:00Z`)-instant);}
  const candidates=[...offsets].map(offset=>nominal-offset).filter(instant=>local(instant)===requested);
  if(candidates.length!==1)throw new Error(candidates.length?'Ta godzina występuje dwukrotnie przy zmianie czasu. Wybierz jednoznaczną godzinę. / This time occurs twice during daylight saving transition. Choose an unambiguous time.':'Ta godzina nie istnieje w wybranej strefie. / This local time does not exist in the selected time zone.');
  return new Date(candidates[0]).toISOString();
}

export function localParts(value:unknown, timezone:string) {
  if(!value)return {date:'',time:''};
  const instant=new Date(String(value));
  if(!Number.isFinite(instant.getTime()))return {date:'',time:''};
  const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(instant).map(v=>[v.type,v.value]));
  return {date:`${p.year}-${p.month}-${p.day}`,time:`${p.hour}:${p.minute}`};
}
/** Display the saved instant in the case time zone, independent of browser locale. */
export function documentTimestamp(value: unknown, lang: string, timezone: string): string {
  if (!value) return '∅';
  const instant = new Date(String(value));
  if (!Number.isFinite(instant.getTime())) return String(value);
  try {
    return new Intl.DateTimeFormat(lang === 'pl' ? 'pl-PL' : 'en-GB', {
      timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    }).format(instant) + ` (${timezone})`;
  } catch { return String(value); }
}
