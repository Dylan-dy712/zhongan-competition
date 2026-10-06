import {Component,type ReactNode} from 'react';

export class PageBoundary extends Component<{children:ReactNode;resetKey:string},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidUpdate(previous:Readonly<{children:ReactNode;resetKey:string}>){
    if(this.state.failed && previous.resetKey!==this.props.resetKey)this.setState({failed:false});
  }
  render(){
    if(this.state.failed)return <main className="start-screen" role="alert"><h1>这个页面暂时没能打开</h1>
      <p>可以切换到其他页面，或重新加载后再试。已经保存的对话不受影响。</p>
      <button onClick={()=>window.location.reload()}>重新加载</button></main>;
    return this.props.children;
  }
}
