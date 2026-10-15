import reading from '../../../output_dir/product-design/assets/nuan-reading-v1.webp';
import {DemoIcon} from './DemoPages';

export default function OriginalChatWelcome(){return <section className="nuan-welcome" aria-label="暖暖陪你看懂资料"><div className="nuan-welcome-copy"><span className="nuan-welcome-kicker"><DemoIcon name="leaf"/>暖暖，陪你一起</span><h2>看懂一点，<br/>安心一点。</h2><p>看病后的疑问，一件一件聊。</p></div><img src={reading} width="100" height="110" alt="捧着笔记本的暖暖"/></section>;}
