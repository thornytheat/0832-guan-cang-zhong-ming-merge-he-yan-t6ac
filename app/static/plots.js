import {element} from './client.js';

function block(target,className,content) {
  const node=element('div',content,{class:className});
  target.append(node);
  return node;
}
const note=(target,text)=>block(target,'chart-note',text);

export function visualize(report,selected) {
  const target=document.querySelector('#visual');
  target.replaceChildren();
  const measurement=report.cases?.find(row=>row.case===selected)?.measure;
  if (!measurement) {block(target,'chart-note','选择有计算值的分组');return;}
  const e=measurement.evidence;

  const box=block(target,'author-cards');
  for(const [anchor,authors] of Object.entries(e.clusters)) {
    const card=block(box,'author-index',`主键 ${anchor}`); block(card,'author-members',authors.join(' · '));
  }
  for(const [edge,reason] of Object.entries(e.blocked)) note(target,`${edge} · ${reason}`);
}
