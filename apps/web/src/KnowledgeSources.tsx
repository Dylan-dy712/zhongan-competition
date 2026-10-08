import type {KnowledgeSource} from './types';

export default function KnowledgeSources({sources=[]}:{sources?:KnowledgeSource[]}) {
  if(!sources.length)return null;
  return <details className="analysis-narrative-sources knowledge-sources">
    <summary>参考知识与出处 <span>{sources.length}</span></summary>
    <div>{sources.map(source=><section key={source.entry_id}>
      <strong>{source.title}</strong><p>{source.source || '用户提供的专业参考资料'}</p>
      <small>{source.scope}</small>
    </section>)}</div>
  </details>;
}
