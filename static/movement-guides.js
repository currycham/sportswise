'use strict';
// Category-level concepts drawn as code; these are not personalized technique demonstrations.
(()=>{
 const safe=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const pose=(head,body,arms,legs)=>`<circle cx="${head[0]}" cy="${head[1]}" r="9"/><path d="${body}"/><path d="${arms}"/><path d="${legs}"/>`;
 const art={
 squat:[pose([70,32],'M70 43V88','M70 54L95 58','M70 88L60 122H88'),pose([210,58],'M210 69L190 89','M205 72L236 72','M190 89L218 105L210 122H235')],
 hinge:[pose([70,32],'M70 43V88','M70 52L85 84','M70 88L60 122H85'),pose([235,66],'M225 70L193 91','M222 73L217 106','M193 91L205 108L204 122H228')],
 push:[pose([68,50],'M75 62L95 96','M79 66L104 69L114 51','M95 96L100 123H121'),pose([208,50],'M215 62L235 96','M219 66L253 51','M235 96L240 123H261')],
 pull:[pose([70,35],'M70 46V91','M70 57L105 65','M70 91L57 123M70 91L85 123'),pose([210,35],'M210 46V91','M210 57L233 69L219 75','M210 91L197 123M210 91L225 123')],
 lunge:[pose([70,33],'M70 44V87','M70 55L56 77M70 55L83 77','M70 87L45 123M70 87L95 123'),pose([210,49],'M210 60V92','M210 69L195 86M210 69L225 86','M210 92L234 93L234 123H251M210 92L182 114L173 119')],
 core:[pose([70,35],'M70 46V93','M70 60L85 65L70 73','M70 93L55 123M70 93L85 123'),pose([210,35],'M210 46V93','M210 60L245 66','M210 93L195 123M210 93L225 123')],
 locomotion:[pose([70,47],'M70 58L65 87','M69 65L50 74M69 65L89 58','M65 87L42 117M65 87L88 105L95 123'),pose([210,30],'M210 41L211 80','M210 51L193 35M210 51L228 35','M211 80L194 105M211 80L230 105')],
 throw:[pose([70,40],'M70 51V91','M70 63L92 69L87 58','M70 91L56 124M70 91L84 124'),pose([210,40],'M210 51L215 91','M210 63L252 57','M215 91L200 124M215 91L231 124')],
 };
 art.run=[pose([70,47],'M70 58L65 87','M69 65L50 74M69 65L89 58','M65 87L42 117M65 87L88 105L95 123'),pose([218,42],'M215 53L205 82','M213 59L232 72M213 59L195 55','M205 82L226 98L241 94M205 82L187 111')];
 art.jump=[pose([70,40],'M70 51V88','M70 60L55 78M70 60L85 78','M70 88L58 122H73M70 88L84 122H97'),pose([210,30],'M210 41L211 80','M210 51L193 35M210 51L228 35','M211 80L194 105M211 80L230 105')];
 art.chair_stand=[
  '<g data-guide-prop="chair"><path d="M43 58V125M43 91H77V125" stroke="#93a27e" stroke-width="4"/></g>'+pose([66,49],'M66 60L63 89','M65 68L88 73','M63 89H91V124H108'),
  '<g data-guide-prop="chair"><path d="M183 58V125M183 91H217V125" stroke="#93a27e" stroke-width="4"/></g>'+pose([231,30],'M231 41L228 85','M230 53L249 67','M228 85L235 124H252')
 ];
 art.heel_raise=[
  '<g data-guide-prop="wall"><path d="M105 23V125" stroke="#93a27e" stroke-width="4"/></g>'+pose([61,32],'M61 43V88','M61 57L105 58','M61 88V124H82'),
  '<g data-guide-prop="wall"><path d="M245 23V125" stroke="#93a27e" stroke-width="4"/></g>'+pose([201,25],'M201 36V81','M201 50L245 51','M201 81V115L222 124')+'<path d="M201 124V117" stroke="#93a27e" stroke-width="2" stroke-dasharray="2 3"/>'
 ];
 const categories={
 run:{name:'步行与跑步类',labels:['准备迈步','稳定推进'],points:['先选熟悉的路线，逐步进入课表强度。','以稳定可控制的节奏移动，不照图模仿固定步幅或关节角度。'],check:'简图表达行进方向，不是个体跑姿分析。'},
 jump:{name:'跳跃类',labels:['站稳准备','向上移动'],points:['先确认落地与退出空间，使用熟悉且可控制的版本。','起跳与落地优先保证动作质量，跳箱时按文字要求下箱。'],check:'简图不规定箱高；质量下降时停组。'},
 chair_stand:{name:'椅子坐站',labels:['坐稳脚踩地','站起后再坐回'],points:['使用稳固、不会滑动的椅子，椅背靠墙；双脚踩稳地面。','身体轻向前，平稳站起，再缓慢坐回；需要时用手辅助。'],check:'侧面位置简图；椅子高度与幅度按本次文字要领调整。'},
 heel_raise:{name:'扶稳提踵',labels:['扶稳脚跟落地','脚跟缓慢抬起'],points:['站在固定支撑旁，手轻扶稳，双脚前脚掌保持踩地。','双脚脚跟缓慢抬起，再控制放回；不弹跳，也不把重量挂在手臂上。'],check:'侧面位置简图；保持平衡，在舒服范围内抬起。'},
 squat:{name:'蹲类',labels:['站稳准备','屈髋屈膝'],points:['脚底保持稳定，膝盖随脚尖方向移动。','只下蹲到当前能控制且舒服的幅度，再平稳站起。'],check:'不要为了追求深度失去脚底或躯干控制。'},
 hinge:{name:'髋铰链类',labels:['站稳准备','髋向后移'],points:['膝盖微屈，让髋部带动躯干前倾。','保持背部自然，按本动作要求控制负重路径。'],check:'示意图不规定俯身深度；不以腰背弯曲追求更低的位置。'},
 push:{name:'推类',labels:['稳定支撑','推离支撑'],points:['先稳住支撑和躯干，再按课程要求推出。','以能控制的幅度回程，避免耸肩和借力。'],check:'这是推的动作方向示意；墙推、卧推和过头推的支撑方式不同。'},
 pull:{name:'拉类',labels:['准备伸展','拉近身体'],points:['按本动作要求先稳住支撑，再把手肘沿合适路径拉回。','控制回程，不甩动身体追赶次数。'],check:'示意为拉的方向；引体、绳索和哑铃划船应分别按文字要领操作。'},
 lunge:{name:'弓步与分腿蹲类',labels:['分腿站稳','控制下降'],points:['先找到稳定站距，需要时使用固定支撑。','按课程规定屈髋屈膝，前脚踩稳再回到起点。'],check:'图中不是固定步幅或深度，不要求膝盖触地。'},
 core:{name:'抗旋与核心控制类',labels:['稳住躯干','四肢移动'],points:['呼吸自然，先让躯干保持稳定。','按本动作规定移动四肢或保持姿势，不用腰背代偿。'],check:'此图仅解释稳住躯干的概念；死虫、侧桥、抗旋各有不同体位。'},
 locomotion:{name:'跑与跳的移动类',labels:['稳定准备','移动方向'],points:['跑步按课表强度稳定推进；跳跃先确认落地与退出空间。','跳跃动作优先保证起跳和落地质量，动作质量下降时停组。'],check:'这是移动方向概念图，不提供跑姿、跳箱高度或落地姿势的精确指导。'},
 throw:{name:'投掷类',labels:['稳定准备','向目标投出'],points:['先确认器械、方向、反弹和周围空间适合该动作。','保持支撑稳定，按课表规定投出后安全接回或复位。'],check:'球的种类与动作熟练度影响做法；此图不能替代药球传球的实际教学。'},
 };
 function classify(title,pattern=''){
  if(/抓举|挺举|翻举|上杠|双力臂|倒立|AMRAP|循环|综合|HYROX|CrossFit|土耳其|游泳/i.test(title))return null;
  const text=title+' '+pattern;
  if(/椅子坐站|坐站|坐到站/.test(text))return 'chair_stand';
  if(/扶稳提踵|扶墙提踵|站姿提踵|双脚提踵/.test(text))return 'heel_raise';
  if(/投|传球|掷/.test(text))return 'throw';
  if(/跑|步行|快走/.test(text)&&!/分腿|弓步/.test(text))return 'run';
  if(/跳/.test(text))return 'jump';
  if(/弓步|分腿|登阶|台阶/.test(text))return 'lunge';
  if(/硬拉|RDL|髋铰链|髋折叠|早安/i.test(text))return 'hinge';
  if(/抗旋|Pallof|死虫|侧桥|平板|核心/i.test(text))return 'core';
  if(/蹲/.test(text))return 'squat';
  if(/划船|引体|下拉|水平拉|垂直拉/.test(text))return 'pull';
  if(/俯卧撑|卧推|推举|胸前推|水平推|垂直推/.test(text))return 'push';
  return null;
 }
 function render(title,pattern=''){
  const key=classify(title,pattern),guide=categories[key];
  if(!guide)return `<p class="guide-disclaimer">这个动作暂未提供配图。请结合本次文字要领；复杂技能向合格教练核对实际做法。</p>`;
  return `<figure class="movement-figure"><svg class="movement-svg" viewBox="0 0 300 160" role="img" aria-label="${safe(guide.name)}类别示意：${safe(guide.labels.join('，'))}"><defs><marker id="guide-arrow-${key}" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0 0L6 3L0 6" fill="none" stroke="#829b5d"/></marker></defs><path d="M20 125H280" stroke="#dde5d0" stroke-width="2"/><g fill="none" stroke="#3e5c3c" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">${art[key].join('')}</g><path d="M120 55H166" fill="none" stroke="#829b5d" stroke-width="3" marker-end="url(#guide-arrow-${key})"/><g fill="#41583b" font-size="12" text-anchor="middle"><text x="70" y="150">${safe(guide.labels[0])}</text><text x="218" y="150">${safe(guide.labels[1])}</text></g></svg><figcaption>${safe(guide.name)} · 动作方向简图，以本次文字要领为准</figcaption></figure><ol>${guide.points.map(p=>`<li>${safe(p)}</li>`).join('')}</ol><p class="guide-disclaimer">${safe(guide.check)}</p>`;
 }
 globalThis.SportsWiseMovementGuides={classify,render};
})();
