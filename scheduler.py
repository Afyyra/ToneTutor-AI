"""Local time-slot suggestions and optional Google Calendar OAuth for a LOCAL desktop demo.
No existing events are altered. Only free/busy blocks are read (never event titles).
"""
from datetime import datetime, date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from runtime_tls import validate_ca_bundle

HERE=Path(__file__).parent
CLIENT_FILE=HERE/'credentials.json'
TOKEN_FILE=HERE/'google_token.json'
SCOPES=['https://www.googleapis.com/auth/calendar.freebusy',
        'https://www.googleapis.com/auth/calendar.events.owned']

def connected():
    return TOKEN_FILE.exists()

def credentials():
    validate_ca_bundle()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if not TOKEN_FILE.exists(): raise RuntimeError('Google Calendar is not connected')
    creds=Credentials.from_authorized_user_file(str(TOKEN_FILE),SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request());TOKEN_FILE.write_text(creds.to_json(),encoding='utf-8')
    if not creds.valid: raise RuntimeError('Google Calendar credentials expired. Reconnect.')
    return creds

def connect_local():
    """Open browser for localhost OAuth. Do NOT use this local flow on a public server."""
    validate_ca_bundle()
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENT_FILE.exists(): raise FileNotFoundError('Missing credentials.json. Follow README setup.')
    flow=InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE),SCOPES)
    creds=flow.run_local_server(port=0,open_browser=True)
    TOKEN_FILE.write_text(creds.to_json(),encoding='utf-8')
    return True

def disconnect():
    if TOKEN_FILE.exists():TOKEN_FILE.unlink()

def service():
    validate_ca_bundle()
    from googleapiclient.discovery import build
    return build('calendar','v3',credentials=credentials(),cache_discovery=False)

def freebusy(start,end,api=None):
    api=api or service()
    result=api.freebusy().query(body={
      'timeMin':start.isoformat(), 'timeMax':end.isoformat(),
      'timeZone':getattr(start.tzinfo,'key','UTC'),
      'items':[{'id':'primary'}]}).execute()
    cal=result.get('calendars',{}).get('primary',{})
    if cal.get('errors'):raise RuntimeError('Calendar availability could not be verified')
    return [(datetime.fromisoformat(r['start'].replace('Z','+00:00')),
             datetime.fromisoformat(r['end'].replace('Z','+00:00'))) for r in cal.get('busy',[])]

def overlaps(start,end,busy):
    return any(start < end_busy and end > start_busy for start_busy,end_busy in busy)

def candidate_slots(now,goal_minutes,preferred_time,busy,days=7,max_results=5):
    """Deterministic shortlist ranked by preferred local time and nearest calendar day."""
    if goal_minutes not in (15,30,45,60):raise ValueError('Invalid goal')
    tz=now.tzinfo
    if tz is None:raise ValueError('Timezone-aware now required')
    hh,mm=map(int,preferred_time.split(':'))
    duration=timedelta(minutes=goal_minutes)
    ranked=[]
    for offset in range(days):
        day=now.date()+timedelta(days=offset)
        preferred=hh*60+mm
        for minutes in range(8*60,22*60-goal_minutes+1,15):
            start=datetime.combine(day,time(minutes//60,minutes%60),tzinfo=tz)
            end=start+duration
            if start<now+timedelta(minutes=5) or overlaps(start,end,busy):continue
            score=(offset,abs(minutes-preferred),minutes)
            ranked.append((score,{'start':start.isoformat(),'end':end.isoformat(),
                                  'day':day.isoformat(),'duration_minutes':goal_minutes}))
    ranked.sort(key=lambda row:row[0])
    return [s for _,s in ranked[:max_results]]

def suggest(goal_minutes,preferred_time,timezone,days=7,api=None,now=None):
    tz=ZoneInfo(timezone)
    now=now or datetime.now(tz)
    bound=now+timedelta(days=days+1)
    busy=freebusy(now,bound,api=api)
    return candidate_slots(now,goal_minutes,preferred_time,busy,days=days)

def create_event(slot,topic,timezone,api=None,now=None):
    """Only call from a UI confirm button, and recheck availability first."""
    api=api or service()
    now=now or datetime.now(ZoneInfo(timezone))
    start=datetime.fromisoformat(slot['start']);end=datetime.fromisoformat(slot['end'])
    if start.tzinfo is None or end.tzinfo is None or not (now<start<end<=start+timedelta(hours=1)):
        raise ValueError('Invalid or expired training slot')
    if overlaps(start,end,freebusy(start,end,api=api)):
        raise RuntimeError('Slot is no longer free. Refresh suggestions.')
    body={'summary':f'ToneTutor AI · {topic[:70]}',
          'description':'Personalised music practice. Created only after user confirmation.',
          'start':{'dateTime':start.isoformat(),'timeZone':timezone},
          'end':{'dateTime':end.isoformat(),'timeZone':timezone},
          'reminders':{'useDefault':False,'overrides':[{'method':'popup','minutes':10}]},
          'visibility':'private'}
    return api.events().insert(calendarId='primary',body=body).execute()


def check_existing_training_conflicts(owned_sessions,api=None):
    """Manual recheck. Reads event times/IDs only; never reads event titles or modifies events."""
    if not owned_sessions:return []
    api=api or service()
    starts=[datetime.fromisoformat(s['begins']) for s in owned_sessions]
    ends=[datetime.fromisoformat(s['ends']) for s in owned_sessions]
    params={'calendarId':'primary','timeMin':min(starts).isoformat(),
            'timeMax':max(ends).isoformat(),'singleEvents':True,
            'maxResults':250,'fields':'nextPageToken,items(id,status,start(dateTime),end(dateTime))'}
    events=[]
    for _ in range(10):
        resp=api.events().list(**params).execute()
        events.extend(resp.get('items',[]))
        token=resp.get('nextPageToken')
        if not token:break
        params['pageToken']=token
    conflicts=[]
    by_id={e.get('id'):e for e in events if e.get('status')!='cancelled'}
    for s in owned_sessions:
        start=datetime.fromisoformat(s['begins']);end=datetime.fromisoformat(s['ends'])
        own=by_id.get(s['event_id'])
        if not own:
            conflicts.append({'topic':s['topic'],'begins':s['begins'],
                              'message':'Training event missing, moved, or cancelled. Review your calendar.'})
            continue
        try:
            actual_start=datetime.fromisoformat(own['start']['dateTime'].replace('Z','+00:00'))
            actual_end=datetime.fromisoformat(own['end']['dateTime'].replace('Z','+00:00'))
        except (KeyError,ValueError):continue
        if actual_start!=start or actual_end!=end:
            conflicts.append({'topic':s['topic'],'begins':s['begins'],'message':'Training event time changed.'})
        if any(e.get('id')!=s['event_id'] and e.get('start',{}).get('dateTime')
               and overlaps(actual_start,actual_end,[(
                   datetime.fromisoformat(e['start']['dateTime'].replace('Z','+00:00')),
                   datetime.fromisoformat(e['end']['dateTime'].replace('Z','+00:00')))])
               for e in events if e.get('status')!='cancelled' and e.get('end',{}).get('dateTime')):
            conflicts.append({'topic':s['topic'],'begins':s['begins'],
                              'message':'Training time now conflicts with another calendar event.'})
    return conflicts
