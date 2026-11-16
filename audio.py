"""Local synthesis. Tones are intentionally piano-like, not recorded piano samples."""
import io
import wave
import numpy as np
from music import frequency

RATE = 22050

def tone(note, seconds=0.55):
    seconds = float(seconds)
    if not 0.08 <= seconds <= 4.0: raise ValueError('Invalid duration')
    t = np.arange(int(RATE*seconds),dtype=np.float64)/RATE
    f = frequency(note)
    signal = sum(np.sin(2*np.pi*f*k*t)*w for k,w in ((1,1.),(2,.25),(3,.12)))
    attack = np.minimum(1.0,t/0.015)
    envelope = attack*np.exp(-2.5*t/seconds)
    envelope[-min(250,len(envelope)):] *= np.linspace(1,0,min(250,len(envelope)))
    return (signal*envelope*0.45).astype(np.float32)

def silence(seconds):
    return np.zeros(int(RATE*seconds),dtype=np.float32)

def sequence(notes, note_seconds=0.6, gap=0.13):
    if len(notes)>16: raise ValueError('Sequence too long')
    if not notes: raise ValueError('Sequence empty')
    chunks=[]
    for n in notes:
        chunks.extend((tone(n,note_seconds),silence(gap)))
    return np.concatenate(chunks)

def wav_bytes(notes, note_seconds=0.6):
    if isinstance(notes,str): notes=[notes]
    a=sequence(notes,note_seconds)
    pcm=np.clip(a,-1,1)
    data=(pcm*32767).astype('<i2').tobytes()
    stream=io.BytesIO()
    with wave.open(stream,'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE); f.writeframes(data)
    return stream.getvalue()

def metronome(bpm=100, beats=8, beats_per_measure=4):
    """Synthesize a click track to demonstrate tempo and time signatures."""
    if not 40<=int(bpm)<=220 or not 1<=int(beats)<=32 or beats_per_measure not in (2,3,4):
        raise ValueError('Invalid metronome settings')
    length=int(RATE*60/int(bpm));chunks=[]
    for i in range(beats):
        click=np.zeros(length,dtype=np.float32)
        count=min(int(.06*RATE),length)
        tt=np.arange(count)/RATE
        freq=1400 if i%beats_per_measure==0 else 850
        click[:count]=(0.32*np.sin(2*np.pi*freq*tt)*np.exp(-40*tt)).astype(np.float32)
        chunks.append(click)
    buf=io.BytesIO()
    with wave.open(buf,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(RATE)
        f.writeframes((np.concatenate(chunks)*32767).astype('<i2').tobytes())
    return buf.getvalue()
