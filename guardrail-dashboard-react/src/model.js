export const roles={planner:'기획자',developer:'개발자',reviewer:'검토자'};
export const states={progress:'진행',stagnant:'정체',oscillating:'왕복',baseline:'기준점',unmeasured:'판단 불가'};
export const issues={requirements:'요구사항','acceptance-review':'인수 검토','status-filter':'상태 필터','search-normalization':'검색 정규화','sort-order':'정렬 순서','filtering-order':'필터 적용 순서','pagination-validation':'페이지 입력값 검증','input-immutability':'입력 데이터 보존'};
export const tools={read_file:'파일 읽기',write_file:'파일 쓰기',replace_in_file:'파일 내용 수정',run_tests:'테스트 실행'};
export const number=x=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('ko-KR'):'미확인';
export function validate(bundle){
 if(!Array.isArray(bundle.steps)||!bundle.steps.length||bundle.steps.some(s=>!s||!Number.isInteger(s.step_id)||typeof s.agent!=='string'))throw Error('steps.json에 올바른 단계 번호와 역할이 필요합니다.');
 if(new Set(bundle.steps.map(s=>s.step_id)).size!==bundle.steps.length)throw Error('중복된 단계 번호가 있습니다.');
 if(bundle.summary&&(!bundle.summary.session_id||bundle.summary.steps!==bundle.steps.length))throw Error('요약과 작업 단계 수가 일치하지 않습니다. 같은 실행 폴더의 파일을 선택하세요.');
 return {...bundle,steps:[...bundle.steps].sort((a,b)=>a.step_id-b.step_id)};
}
export function comparison(data,s){
 const p=s.observation?.progress||{},previousRole=data.steps.find(t=>t.step_id===p.comparison_step_id);
 const before=previousRole?.observed_final_report?.open_issue_ids,now=s.observed_final_report?.open_issue_ids;
 const previous=data.steps[data.steps.indexOf(s)-1],old=previous?.acceptance?.artifact?.file_hashes,current=s.acceptance?.artifact?.file_hashes;
 return {previousRole,before,now,removed:Array.isArray(before)&&Array.isArray(now)?before.filter(x=>!now.includes(x)):null,added:Array.isArray(before)&&Array.isArray(now)?now.filter(x=>!before.includes(x)):null,changed:old&&current?[...new Set([...Object.keys(old),...Object.keys(current)])].filter(k=>old[k]!==current[k]):null};
}
