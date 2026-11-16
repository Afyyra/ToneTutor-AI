"""Vector staff drawing; note positions are diatonic, with ledger lines for out-of-range notes."""
from music import normalise, NATURAL

def diatonic_index(note):
    n=normalise(note)
    return int(n[-1])*7 + NATURAL.index(n[0])

def staff_svg(note,clef='treble',show_name=False):
    if clef not in ('treble','bass'):raise ValueError('Unknown clef')
    n=normalise(note)
    # Treble E4 / bass G2 is the bottom line of a standard 5-line staff.
    reference='E4' if clef=='treble' else 'G2'
    steps=diatonic_index(n)-diatonic_index(reference)
    y=116-10*steps
    lines=''.join(f'<line x1="35" x2="330" y1="{yy}" y2="{yy}" stroke="#607184" stroke-width="1.7"/>' for yy in (36,56,76,96,116))
    ledger=''
    if y>116:
        for yy in range(136,int(y)+1,20): ledger+=f'<line x1="154" x2="202" y1="{yy}" y2="{yy}" stroke="#29394d" stroke-width="2"/>'
    if y<36:
        for yy in range(16,int(y)-1,-20):ledger+=f'<line x1="154" x2="202" y1="{yy}" y2="{yy}" stroke="#29394d" stroke-width="2"/>'
    accidental='<text x="143" y="%s" font-size="23" fill="#263f5f">♯</text>'%(y+7) if '#' in n else ''
    text=f'<text x="215" y="{y+5}" font-size="15" fill="#29394d">{n}</text>' if show_name else ''
    # SVG viewBox supports notes with ledger lines above/below staff.
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="285" viewBox="0 -50 365 245">
    <rect x="0" y="-50" width="365" height="245" rx="12" fill="#f7f9fc"/>
    <text x="22" y="-20" font-size="13" fill="#516479">{clef.title()} clef</text>
    {lines}<text x="47" y="86" font-size="28" fill="#29394d">{'𝄞' if clef=='treble' else '𝄢'}</text>
    {ledger}{accidental}<ellipse cx="178" cy="{y}" rx="11" ry="7" transform="rotate(-18 178 {y})" fill="#29394d"/>
    {text}</svg>'''

def rhythm_svg():
    """Basic note-length illustrations; the browser can display this without music fonts."""
    pieces=[]
    types=[('Whole',4,False,False),('Half',2,False,True),('Quarter',1,True,True),('Eighth',.5,True,True)]
    for i,(name,beats,filled,stem) in enumerate(types):
        x=65+i*110;y=91
        ellipse=f'<ellipse cx="{x}" cy="{y}" rx="12" ry="8" transform="rotate(-20 {x} {y})" stroke="#1d3450" stroke-width="2" fill="{("#1d3450" if filled else "#fff")}"/>'
        line=f'<line x1="{x+11}" y1="{y}" x2="{x+11}" y2="{y-54}" stroke="#1d3450" stroke-width="3"/>' if stem else ''
        flag=f'<path d="M{x+11} {y-54} q 29 10 7 29" fill="none" stroke="#1d3450" stroke-width="3"/>' if i==3 else ''
        pieces.append(ellipse+line+flag+f'<text x="{x}" y="145" text-anchor="middle" font-size="16" fill="#1d3450">{name}</text><text x="{x}" y="164" text-anchor="middle" font-size="13" fill="#536b7d">{beats} beat(s)</text>')
    return '<svg xmlns="http://www.w3.org/2000/svg" width="650" height="235" viewBox="0 0 490 185"><rect width="490" height="185" rx="14" fill="#f5f8fc"/>'+''.join(pieces)+'</svg>'
