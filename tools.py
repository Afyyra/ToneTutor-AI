"""Validated, learner-scoped AI tools. Grading, OAuth and calendar writes are never model tools."""
import json
import random
import database as db
from exercises import SKILLS,LEVELS,EXERCISE_TYPES,generate
from music import ALL_KEYS,LESSON_BY_ID

SUPPORT={
 'pitch':'Pitch = how high or low a sound is, not how loud. Replay both notes and focus on which seems higher.',
 'notes':'Listen to the reference notes. Try matching the same sound or hearing the smallest interval to the target.',
 'intervals':'An interval is a number of semitone steps. One adjacent piano key to the next is one semitone.',
 'theory':'Use the keyboard as a map: sharps and flats name neighbouring keys; scales follow ordered step patterns.',
 'notation':'Treble lines E G B D F and spaces F A C E; bass lines G B D F A and spaces A C E G.',
 'rhythm':'Tap a regular pulse. Quarter notes last one beat in 4/4; half notes two and eighth notes half a beat.',
 'melody':'Listen for whether the tune rises, falls, or repeats. Replay short sections before choosing notes.',
 'piano':'Find middle C (C4), then count adjacent keys including black keys to reach the target.'
}

class LearnerTools:
    def __init__(self,learner_id,source='gemini'):
        self.learner_id=learner_id;self.source=source;self._slots=[];self._chosen=None

    def execute(self,name,arguments=None):
        arguments=arguments or {}
        methods={
            'get_learning_profile':self.get_learning_profile,
            'get_recent_attempts':self.get_recent_attempts,
            'get_note_confusions':self.get_note_confusions,
            'update_learning_plan':self.update_learning_plan,
            'assign_exercise':self.assign_exercise,
            'provide_learning_support':self.provide_learning_support,
            'get_available_lessons':self.get_available_lessons,
            'suggest_training_slots':self.suggest_training_slots,
            'select_training_slot':self.select_training_slot,
        }
        try:
            if name not in methods: raise ValueError('Tool not allowed')
            if not isinstance(arguments,dict): raise ValueError('Arguments must be an object')
            result=methods[name](**arguments)
        except Exception as e:
            result={'error':str(e) if isinstance(e,(ValueError,TypeError,RuntimeError,FileNotFoundError)) else 'Tool execution failed'}
        db.log_tool(self.learner_id,name,arguments,result,self.source)
        return result

    def get_learning_profile(self):
        return db.get_profile(self.learner_id)

    def get_recent_attempts(self,limit=12):
        if not isinstance(limit,int) or not 1<=limit<=30: raise ValueError('limit must be 1–30')
        rows=db.recent_attempts(self.learner_id,limit)
        return {'attempts':[{'skill':r['skill'],'difficulty':r['difficulty'],
                              'target_note':r['note_target'],'submitted':r['submitted'],
                              'correct':bool(r['correct'])} for r in rows]}

    def get_note_confusions(self):
        data=db.note_statistics(self.learner_id)
        return {'notes':{name:item for name,item in data.items() if item['attempts']>0}}

    def get_available_lessons(self):
        return {'lessons':[{'id':key,'title':v['title'],'skill':v['skill']} for key,v in LESSON_BY_ID.items()]}

    def update_learning_plan(self,skill,difficulty,reason,focus_note=None,contrast_note=None):
        if skill not in SKILLS or difficulty not in LEVELS: raise ValueError('Invalid skill/difficulty')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>240: raise ValueError('Provide a short reason')
        if focus_note is not None and focus_note not in ALL_KEYS:raise ValueError('Invalid focus note')
        if contrast_note is not None and contrast_note not in ALL_KEYS:raise ValueError('Invalid contrast note')
        if (focus_note or contrast_note) and skill!='notes': raise ValueError('Focus-note fields only apply to note recognition')
        db.set_plan(self.learner_id,skill,difficulty,reason,focus_note,contrast_note)
        return {'updated':True,'skill':skill,'difficulty':difficulty,'focus_note':focus_note,
                'contrast_note':contrast_note,'reason':reason}

    def assign_exercise(self,skill,difficulty,exercise_type=None):
        plan=db.get_plan(self.learner_id)
        if not plan:raise ValueError('Create the learning plan first')
        if plan['skill']!=skill or plan['difficulty']!=difficulty:
            raise ValueError('Exercise must match active learning plan')
        if exercise_type is not None and exercise_type not in EXERCISE_TYPES[skill]:
            raise ValueError('Unsupported exercise type')
        focus=plan['focus_note'];contrast=plan['contrast_note']
        if not db.get_profile(self.learner_id)['assessment_complete']:
            raise ValueError('Finish the initial assessment first')
        # Check existing active assignment before generating another random exercise.
        old=db.active(self.learner_id)
        if old:return {'assigned':False,'exercise_id':old['id'],'message':'Existing assignment remains active'}
        ex=generate(skill,difficulty,focus_note=focus,contrast_note=contrast,
                    preferred_type=exercise_type or ('contrast_notes' if skill=='notes' and contrast else None))
        out=db.assign(self.learner_id,ex)
        return {'assigned':out['assigned'],'exercise':out['exercise']}

    def provide_learning_support(self,skill,kind='hint'):
        if skill not in SKILLS or kind not in ('hint','explanation'):raise ValueError('Invalid support request')
        text=SUPPORT[skill]
        db.add_support(self.learner_id,text)
        return {'provided':True,'kind':kind,'message':text}

    def suggest_training_slots(self,days=7):
        """Read-only; NEVER creates calendar events. Manual consent required in Streamlit."""
        if not isinstance(days,int) or not 1<=days<=7:raise ValueError('days must be 1–7')
        import scheduler
        if not scheduler.connected():return {'error':'Calendar not connected. User must connect explicitly.'}
        pref=db.preferences(self.learner_id)
        self._slots=scheduler.suggest(pref['goal_minutes'],pref['reminder_time'],pref['timezone'],days)
        return {'slots':[{'index':i,**slot} for i,slot in enumerate(self._slots)]}

    def select_training_slot(self,index,reason):
        """Choose an existing validated free-time suggestion, never create an event."""
        if type(index) is not int or not (0<=index<len(self._slots)):
            raise ValueError('Select an index returned by suggest_training_slots first')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>240:
            raise ValueError('Provide a short scheduling reason')
        self._chosen={'index':index,'reason':reason,'slot':self._slots[index]}
        return {'selected':True,**self._chosen}
