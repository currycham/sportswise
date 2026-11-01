const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function setup(){
 const elements=new Map();
 const el=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',hidden:true,open:false,addEventListener(){},showModal(){this.open=true},close(){this.open=false},classList:{add(){},remove(){}},querySelector(){return null}});return elements.get(id)};
 const ctx={document:{querySelector:el,addEventListener(){}},navigator:{},window:{addEventListener(){}},setTimeout,clearTimeout,setInterval,clearInterval,console,structuredClone,Date,Map,FormData:class{}};
 const source=fs.readFileSync('static/app.js','utf8').replace(/\nload\(\);\s*$/,'');
 vm.runInNewContext(source+'\nglobalThis.ui={set(v){data=v},timer(id){timerSession=id;timerStart=Date.now()-3000},todayPage,feedback,landing};',ctx);
 return {ui:ctx.ui,elements};
}
function fixture(){
 const session={id:'today-session',date:'2026-11-01',kind:'walk',title:'轻松步行',minutes:10,purpose:'找到节奏',steps:[],status:'planned'};
 return {today:'2026-11-01',revision:1,user:{demo:true},capabilities:{ai:true,mail:false},direction:['maintain','先保持当前安排'],notices:[],deliveries:[],stats:{completed:1,planned:1,minutes:8,unknown:0,original_minutes:10,planned_minutes:10},state:{profile:{name:'虚构用户',goal:'habit',days:[6],minutes:15},plan:{week:'2026-10-26',phase:'适应与校准',sessions:[session]},upcoming:null,history:[],records:[],chat:[],reviews:[],settings:{},risk:{level:'none',message:''}}};
}
test('completed card separates actual minutes and planned minutes',()=>{
 const {ui}=setup(),d=fixture();
 d.state.records=[{session_id:'today-session',date:'2026-11-01',status:'partial',minutes:8,effort:'okay'}];ui.set(d);
 const html=ui.todayPage();assert.match(html,/实际 8 分钟/);assert.match(html,/原安排 10 分钟/);assert.match(html,/完成一点/);
});
test('ending timer after seconds defaults to partial, not full completion',()=>{
 const {ui,elements}=setup(),d=fixture();ui.set(d);ui.timer('today-session');ui.feedback('today-session');
 const html=elements.get('#modal').innerHTML;
 assert.match(html,/name="status" value="partial" checked/);
 assert.doesNotMatch(html,/name="status" value="completed" checked/);
 assert.match(html,/name="minutes" value="0"/);
});
test('first visit offers from-zero planning separately from example',()=>{
 const {ui,elements}=setup();ui.landing();const html=elements.get('#app').innerHTML;
 assert.match(html,/data-action="new-demo">先为我制定计划/);
 assert.match(html,/data-action="demo">看看示例计划/);
 assert.match(html,/预览调整/);
});
