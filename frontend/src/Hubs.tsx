import MemoryLab from './MemoryLab';
import MemoryView from './MemoryView';
import PrivacyLab from './PrivacyLab';
import PrivacyView from './PrivacyView';
import {Seg} from './ui';
import {useWorkspace} from './workspace';

/** Memory: the real page, or the guided explanation. One tab switch, no extra top-level navigation. */
export function MemoryHub({lab}: {lab?: string}) {
  const {go} = useWorkspace();
  const mode = lab === undefined ? 'mine' : 'lab';
  return <div className="hub">
    <div className="hubtabs"><Seg label="Memory sections" value={mode} onChange={next => go(next === 'lab' ? {view: 'memory', lab: ''} : {view: 'memory'})}
      options={[{key: 'mine', label: 'My Memories'}, {key: 'lab', label: 'Memory Lab'}]}/></div>
    {mode === 'lab' ? <MemoryLab step={lab ?? ''} onStep={id => go({view: 'memory', lab: id})}/> : <MemoryView/>}
  </div>;
}

/** Privacy: the real inspector, or the guided explanation. */
export function PrivacyHub({txId, lab}: {txId?: string; lab?: string}) {
  const {go} = useWorkspace();
  const mode = lab === undefined ? 'mine' : 'lab';
  return <div className="hub">
    <div className="hubtabs"><Seg label="Privacy sections" value={mode} onChange={next => go(next === 'lab' ? {view: 'privacy', lab: ''} : {view: 'privacy'})}
      options={[{key: 'mine', label: 'My Privacy'}, {key: 'lab', label: 'Privacy Lab'}]}/></div>
    {mode === 'lab' ? <PrivacyLab step={lab ?? ''} onStep={id => go({view: 'privacy', lab: id})}/> : <PrivacyView txId={txId}/>}
  </div>;
}
