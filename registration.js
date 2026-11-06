// CPD Hunter Sprint 1 - local registration profile & state
// Profile and registration state are stored only in this browser (localStorage).
// Nothing is sent to any server.

const PROFILE_KEY = "regProfile";
const REGSTATE_KEY = "regState";
const PROFILE_VERSION = 1;
const REQUIRED = ["title","englishName","email","organisation","primaryDiscipline"];

function loadProfile(){
  try{ return JSON.parse(localStorage.getItem(PROFILE_KEY)) || null; }catch{ return null; }
}
function saveProfile(p){
  p.version = PROFILE_VERSION;
  try{ localStorage.setItem(PROFILE_KEY, JSON.stringify(p)); }catch{}
}
function deleteProfile(){
  try{ localStorage.removeItem(PROFILE_KEY); }catch{}
}
function profileComplete(p){
  if(!p) return false;
  return REQUIRED.every(k => (p[k]||"").toString().trim());
}
function exportProfile(){
  const p = loadProfile();
  if(!p){ alert("\u5514\u8a3b\u518a\u6a94\u6848\u53ef\u532f\u51fa"); return; }
  const blob = new Blob([JSON.stringify(p,null,2)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "cpd-hunter-registration-profile.json";
  a.click();
  URL.revokeObjectURL(a.href);
}
function importProfile(file){
  return new Promise((resolve,reject)=>{
    const r = new FileReader();
    r.onload = ()=>{
      try{
        const data = JSON.parse(r.result);
        if(typeof data !== "object" || data === null || Array.isArray(data))
          throw new Error("invalid");
        if(data.version !== PROFILE_VERSION)
          throw new Error("version");
        const clean = {version: PROFILE_VERSION};
        const allowed = ["title","englishName","chineseName","email","phone","position","organisation","hkieNumber","primaryDiscipline","secondaryDiscipline","preferredLanguage"];
        for(const k of allowed){
          if(typeof data[k] === "string") clean[k] = data[k].slice(0,200);
        }
        if(!profileComplete(clean))
          throw new Error("incomplete");
        saveProfile(clean);
        resolve(clean);
      }catch(e){ reject(e); }
    };
    r.onerror = ()=>reject(new Error("read"));
    r.readAsText(file);
  });
}

function loadRegState(){
  try{ return JSON.parse(localStorage.getItem(REGSTATE_KEY)) || {}; }catch{ return {}; }
}
function saveRegState(s){
  try{ localStorage.setItem(REGSTATE_KEY, JSON.stringify(s)); }catch{}
}
function setRegState(eventId, state, note){
  const all = loadRegState();
  all[eventId] = {state, ts: new Date().toISOString(), note: note||""};
  saveRegState(all);
}
function getRegState(eventId){
  return loadRegState()[eventId] || null;
}

window.RegistrationAdapter = {
  canHandle(url){ return false; },
  inspect(){ return null; },
  matchFields(){ return []; },
  fill(){ /* disabled in Sprint 1 */ },
  validate(){ return {ok:false, reason:"Sprint 1: no auto-fill"}; },
  getUnsupportedFields(){ return []; }
};
