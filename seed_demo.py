"""Seed two explicitly simulated profiles for the five-minute competition video.
No fabricated logs are marked as Gemini. The learners' assessment/answer history is simulated.
"""
import database as db
from exercises import generate


def add_note(learner,target,submitted):
    ex=generate('notes','easy',focus_note=target,contrast_note='D4',preferred_type='contrast_notes')
    ex['notes']=[target];ex['correct_answer']=target
    ex['options']=[target,submitted] if target!=submitted else [target,'E4']
    db.assign(learner,ex);db.submit(learner,submitted)


def add_theory(learner,correct):
    ex=generate('theory','easy')
    db.assign(learner,ex)
    result=ex['correct_answer'] if correct else next(x for x in ex['options'] if x!=ex['correct_answer'])
    db.submit(learner,result)


def main():
    db.initialize()
    for learner in ('SIMULATED-C-D','SIMULATED-THEORY'):
        db.ensure_learner(learner)
        if db.recent_attempts(learner,1):
            print(learner,'already has data; skipped.')
            continue
        if learner=='SIMULATED-C-D':
            for submitted in ('D4','D4','D4','C4'):add_note(learner,'C4',submitted)
            for _ in range(3):add_theory(learner,True)
        else:
            for target in ('C4','D4','E4','F4'):add_note(learner,target,target)
            for correct in (False,False,True,False):add_theory(learner,correct)
        db.mark_assessment_done(learner)
        print('Created',learner,'with SIMULATED performance history.')

if __name__=='__main__':main()
