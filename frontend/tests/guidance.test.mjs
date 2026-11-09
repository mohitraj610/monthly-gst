import test from 'node:test';
import assert from 'node:assert/strict';
import { answerGuide, explainRow, guideStep, moneyLabel } from '../src/guidance.ts';

const row = {status:'tax_head_difference',books:[{number:'INV-1002',values:{taxable:'1000.00',igst:'0.00',cgst:'90.00',sgst:'90.00',cess:'0.00',total:'1180.00'},itc:'UNKNOWN'}],portal:[{number:'INV-1002',values:{taxable:'1000.00',igst:'180.00',cgst:'0.00',sgst:'0.00',cess:'0.00',total:'1180.00'},itc:'Y'}],differences:[{field:'igst'},{field:'cgst'},{field:'sgst'}]};

test('explains actual heads without declaring either source correct',()=>{
  const e=explainRow(row);
  assert.match(e.detail,/CGST ₹90.00/);
  assert.match(e.detail,/SGST\/UTGST ₹90.00/);
  assert.match(e.detail,/portal file shows IGST ₹180.00/);
  assert.match(e.unchanged,/has not changed either file/);
  assert.match(e.next,/original invoice/);
});
test('user misconception is corrected explicitly',()=>{
  for(const q of ['Our code corrected the register, right?','Which is wrong?','Did you fix it?','Change this to IGST']) {
    const answer=answerGuide(q,{row});
    assert.match(answer,/has not changed either file/);
    assert.match(answer,/not a corrected output/);
  }
});
test('two copies are source provenance, not two extra bills',()=>{
  const answer=answerGuide('Why two cards for this invoice?',{row});
  assert.match(answer,/same invoice/);
  assert.match(answer,/not two extra bills/);
});
test('duplicate explanation preserves all entries',()=>{
  const duplicate={...row,status:'duplicate',books:[row.books[0],row.books[0]]};
  assert.match(explainRow(duplicate).detail,/2 entries in your books; 1 in the portal/);
  assert.match(answerGuide('Why two copies?',{row:duplicate}),/not chosen a winner/);
});
test('agreement with unavailable ITC never becomes permission to claim',()=>{
  const exact={...row,status:'exact',portal:[{...row.portal[0],itc:'N'}]};
  assert.match(explainRow(exact).title,/flag needs attention/);
  assert.match(answerGuide('Can I claim ITC?',{row:exact}),/flag says ITC is unavailable/);
  assert.match(answerGuide('Can I claim ITC?',{row:exact}),/does not decide/);
});
test('missing counterpart does not imply supplier non-filing',()=>{
  assert.match(explainRow({...row,status:'books_only',portal:[]}).detail,/does not establish/);
});
test('guidance leaves source facts unchanged',()=>{
  const before=structuredClone(row);
  answerGuide('Explain the difference',{row}); guideStep({row,sample:true}); explainRow(row);
  assert.deepEqual(row,before);
});
test('stale results gate guidance before sample or review actions',()=>{
  assert.equal(guideStep({row,stale:true,sample:true}).action,'reconcile');
  assert.equal(guideStep({phase:'export',stale:true}).action,'reconcile');
});
test('changed sample facts do not trigger a canned amount claim',()=>{
  const changed={...row,portal:[{...row.portal[0],values:{...row.portal[0].values,total:'999.00'}}]};
  assert.equal(guideStep({row:changed,sample:true}).action,'note');
  assert.doesNotMatch(guideStep({row:changed,sample:true}).text,/Both totals/);
});
test('a missing portal record is not invented in the source explanation',()=>{
  assert.match(answerGuide('Why two copies?',{row:{...row,status:'books_only',portal:[]}}),/0 from the portal/);
});
test('review and export questions are not mistaken for source-copy questions',()=>{
  assert.match(answerGuide('How do I record a review note?',{row}),/does not clear the difference/);
  assert.match(answerGuide('How do I export original records?',{row}),/creates a ZIP/);
});
test('workflow walks through imports before reconciliation',()=>{
  assert.equal(guideStep({}).action,'sample');
  assert.equal(guideStep({workspace:true}).action,'books');
  assert.equal(guideStep({workspace:true,hasBooks:true}).action,'portal');
  assert.equal(guideStep({workspace:true,hasBooks:true,hasPortal:true}).action,'reconcile');
});
test('unknown questions are admitted and guide is not presented as AI',()=>{
  assert.match(answerGuide('weather in Delhi',{}),/don’t have an answer/);
  assert.match(answerGuide('Which AI model are you?',{}),/not a general AI model/);
});
test('large values stay exact strings and missing amounts stay unknown',()=>{
  assert.equal(moneyLabel('1000000000000000.01'),'₹1,00,00,00,00,00,00,000.01');
  assert.equal(moneyLabel(null),'Unknown');
});
