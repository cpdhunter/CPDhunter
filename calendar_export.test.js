const assert=require('assert'); const C=require('./calendar_export');
const e={id:'x1',name:'Safety, Risk; and \\ Practice',date:'2026-11-12',time:'19:00-21:00',org:'OSHC',venue:'Online',hrs:2,hrs_est:false,url:'https://example.com/e'};
const ics=C.createICS(e,{category:'H&S',now:new Date('2026-11-01T00:00:00Z')});
assert(ics.includes('BEGIN:VCALENDAR\r\n')); assert(ics.includes('DTSTART;TZID=Asia/Hong_Kong:20261112T190000')); assert(ics.includes('DTEND;TZID=Asia/Hong_Kong:20261112T210000')); assert(ics.includes('TRIGGER:-PT30M')); assert(ics.includes('UID:x1@cpdhunter')); assert(!ics.includes('email'));
const day=C.createICS({...e,time:''}); assert(day.includes('DTSTART;VALUE=DATE:20261112')); assert(day.includes('DTEND;VALUE=DATE:20261113'));
const one=C.createICS({...e,time:'19:00'}); assert(one.includes('DTSTART;TZID=Asia/Hong_Kong:20261112T190000')); assert(!one.includes('DTEND;TZID=Asia/Hong_Kong'));
assert(C.safeFilename(e.name).endsWith('.ics')); console.log('calendar_export tests PASS');
