"""Streamlit v2 WebAudio keyboard: instant playback + each key-press returned to Python.
Only code-owned markup and validated note labels are used. No LLM HTML/JS injection.
"""
import json
import streamlit as st

HTML = '<div id="tt-piano" class="tt-piano"></div>'
CSS = '''
.tt-piano {max-width:780px;overflow-x:auto;padding:12px 4px;}
.tt-label {font-size:14px;font-weight:650;margin-bottom:6px;color:var(--st-text-color);}
.tt-keyboard {position:relative;width:672px;height:175px;display:flex;user-select:none;}
.tt-white {position:relative;width:48px;height:172px;flex:none;background:linear-gradient(white,#eee);color:#172336;
 border:1px solid #a9adb3;border-radius:0 0 7px 7px;cursor:pointer;}
.tt-black {position:absolute;top:0;width:30px;height:107px;background:linear-gradient(#394153,#101720);
 color:white;border:1px solid #1d2330;border-radius:0 0 5px 5px;z-index:2;cursor:pointer;}
.tt-white:hover {background:#d9ecfa} .tt-black:hover{background:#526e91}
.tt-white:active,.tt-white.target{background:#bce3ee}
.tt-black:active,.tt-black.target{background:#4476a9}
.tt-keyname{position:absolute;bottom:8px;left:0;right:0;text-align:center;font-size:11px;font-weight:600;pointer-events:none;}
.tt-black .tt-keyname{bottom:9px;font-size:10px;}
.tt-info{font-size:12px;color:var(--st-text-color);margin-top:6px;}
'''
JS = r'''
export default function(component) {
  const { parentElement, setTriggerValue, data } = component;
  const root=parentElement.querySelector('#tt-piano');
  if(!root) return;
  root.replaceChildren();
  const title=document.createElement('div');title.className='tt-label';title.textContent='Virtual piano · C4 to B5';root.appendChild(title);
  const keyboard=document.createElement('div');keyboard.className='tt-keyboard';root.appendChild(keyboard);
  const info=document.createElement('div');info.className='tt-info';info.textContent='Tap keys to hear a note and send it to the training system.';root.appendChild(info);
  const names=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
  const whiteNames=['C','D','E','F','G','A','B'];
  let audioContext=null;
  function play(m){
    try {
      audioContext=audioContext || new (window.AudioContext||window.webkitAudioContext)();
      if(audioContext.state==='suspended') audioContext.resume();
      const osc=audioContext.createOscillator();const gain=audioContext.createGain();
      osc.type='sine';osc.frequency.value=440*Math.pow(2,(m-69)/12);
      osc.connect(gain);gain.connect(audioContext.destination);
      const now=audioContext.currentTime;
      gain.gain.setValueAtTime(0.001,now);
      gain.gain.exponentialRampToValueAtTime(0.24,now+0.014);
      gain.gain.exponentialRampToValueAtTime(0.001,now+0.5);
      osc.start(now);osc.stop(now+0.52);
    } catch(err) {info.textContent='Audio unavailable in this browser: '+err.message;}
  }
  function makeKey(label,m,black,left){
    const b=document.createElement('button');b.type='button';b.className=black?'tt-black':'tt-white';
    if(black)b.style.left=left+'px';
    if(data && data.target===label)b.classList.add('target');
    b.setAttribute('aria-label','Play '+label);
    const span=document.createElement('span');span.className='tt-keyname';
    span.textContent=(data && data.hideLabels)?'':label;
    b.appendChild(span);
    b.onclick=()=>{play(m);info.textContent='Played: '+label;if(data && data.coachEvent){setTriggerValue('played_event',JSON.stringify({note:label,id:Date.now()+'-'+Math.random()}));}else{setTriggerValue('played',label);}};
    keyboard.appendChild(b);
  }
  let whiteIndex=0;
  for(let m=60;m<=83;m++){
    const name=names[m%12],oct=Math.floor(m/12)-1,label=name+oct;
    if(!name.includes('#')){makeKey(label,m,false);whiteIndex++;}
    else{makeKey(label,m,true,whiteIndex*48-15);}
  }
}
'''
PIANO = st.components.v2.component('tonetutor_piano',html=HTML,css=CSS,js=JS)

def render_piano(key='piano',target=None,hide_labels=False):
    result=PIANO(key=key,data={'target':target or '', 'hideLabels':hide_labels},on_played_change=lambda:None)
    return getattr(result,'played',None)


def render_piano_event(key='coach-piano',target=None):
    """Return a unique key-press event, including identity to prevent Streamlit rerun duplication."""
    result=PIANO(key=key,data={'target':target or '', 'hideLabels':False,'coachEvent':True},
                 on_played_event_change=lambda:None,on_played_change=lambda:None)
    raw=getattr(result,'played_event',None)
    if not isinstance(raw,str):return None
    try:
        event=json.loads(raw)
        if isinstance(event,dict) and isinstance(event.get('id'),str):
            return {'note':event.get('note'),'id':event['id']}
    except (ValueError,TypeError):pass
    return None
