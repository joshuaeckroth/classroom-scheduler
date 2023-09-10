from ortools.sat.python import cp_model
import pandas as pd
import re

kb = {
    "required_courses": ["CSCI 141-01", "CSCI 141-02", "CSCI 142", "CSCI 211", "CSCI 221"],
    "teacher_course_map": {
        "CSCI 141-01": ["AJ", "Josh"],
        "CSCI 141-02": ["AJ", "Josh"],
        "CSCI 142": ["AJ"],
        "CSCI 211": ["Tom"],
        "CSCI 221": ["Josh"],
    },
    "times": ["MWF 11:00-11:50am", "MWF 1:30-2:20pm", "MWF 2:30-3:20pm", "MWF 3:30-4:20pm",
              "TTh 11:30am-12:45pm", "TTh 1:00-2:15pm"],
    "rooms": ["EH 205", "EH 210", "EH 209"]
}

earliest_30min_block = -1
latest_30min_block = -1

def parse_time(t):
    m = re.match(r'((?:M|T|W|Th|F)+) ([0-9]+):([0-9]+)(am|pm)?-([0-9]+):([0-9]+)(am|pm)', t)
    days = re.findall(r'[A-Z][a-z]*', m.group(1))
    start_hour = int(m.group(2))
    start_minute = int(m.group(3))
    start_am_pm = m.group(4)
    end_hour = int(m.group(5))
    end_minute = int(m.group(6))
    end_am_pm = m.group(7)
    if start_am_pm is None:
        start_am_pm = end_am_pm
    if start_am_pm == 'pm' and start_hour != 12:
        start_hour += 12
    if end_am_pm == 'pm' and end_hour != 12:
        end_hour += 12
    # convert hours/minutes to minutes since midnight
    start_30min_block = start_hour * 60 + start_minute
    end_30min_block = end_hour * 60 + end_minute
    # round to nearest 30 minutes
    start_30min_block = int(round(start_30min_block / 30.0))
    end_30min_block = int(round(end_30min_block / 30.0))
    # check if this is the earliest/latest time
    global earliest_30min_block
    global latest_30min_block
    if earliest_30min_block == -1 or start_30min_block < earliest_30min_block:
        earliest_30min_block = start_30min_block
    if latest_30min_block == -1 or end_30min_block > latest_30min_block:
        latest_30min_block = end_30min_block
    return {
        'days': days,
        'start_30min_block': start_30min_block,
        'end_30min_block': end_30min_block,
    }

opt_model = cp_model.CpModel()

time_30min_blocks = {}
for timestr in kb['times']:
    parsed = parse_time(timestr)
    for day in parsed['days']:
        time_30min_blocks[day] = {}
        for i in range(parsed['start_30min_block'], parsed['end_30min_block']):
            time_30min_blocks[day][i] = opt_model.NewBoolVar(f'{day}_{i}')

teacher_time_30min_blocks = {}
course_teacher = {}

for course in kb['required_courses']:
    for teacher in kb['teacher_course_map'][course]:
        course_teacher[(course, teacher)] = opt_model.NewBoolVar(f'{course}_{teacher}')

course_teacher_timestr = {}
for timestr in kb['times']:
    for course in kb['required_courses']:
        for teacher in kb['teacher_course_map'][course]:
            course_teacher_timestr[(course, teacher, timestr)] = opt_model.NewBoolVar(f'{course}_{teacher}_{timestr}')
            opt_model.AddImplication(course_teacher_timestr[(course, teacher, timestr)],
                                     course_teacher[(course, teacher)])
            opt_model.AddImplication(course_teacher[(course, teacher)].Not(),
                                     course_teacher_timestr[(course, teacher, timestr)].Not())
            parsed = parse_time(timestr)
            for day in parsed['days']:
                for i in range(parsed['start_30min_block'], parsed['end_30min_block']):
                    teacher_time_30min_blocks[(course, teacher, day, i)] = opt_model.NewBoolVar(f'{course}_{teacher}_{day}_{i}')
                    opt_model.AddImplication(course_teacher_timestr[(course, teacher, timestr)],
                                             teacher_time_30min_blocks[(course, teacher, day, i)])

# ensure that each course is covered
for course in kb['required_courses']:
    course_sum_vars = []
    for teacher in kb['teacher_course_map'][course]:
        for timestr in kb['times']:
            course_sum_vars.append(course_teacher_timestr[(course, teacher, timestr)])
    opt_model.Add(sum(course_sum_vars) >= 1)

# ensure each course has one teacher
for course in kb['required_courses']:
    for teacher1 in kb['teacher_course_map'][course]:
        for teacher2 in kb['teacher_course_map'][course]:
            if teacher1 != teacher2:
                opt_model.AddImplication(course_teacher[(course, teacher1)], course_teacher[(course, teacher2)].Not())
                opt_model.AddImplication(course_teacher[(course, teacher2)], course_teacher[(course, teacher1)].Not())

# ensure that each teacher is only teaching one course at each time of day
for teacher in kb['teacher_course_map'].keys():
    for timestr in kb['times']:
        parsed = parse_time(timestr)
        for day in parsed['days']:
            for i in range(parsed['start_30min_block'], parsed['end_30min_block']):
                teacher_sum_vars = []
                for course in kb['required_courses']:
                    if teacher in kb['teacher_course_map'][course] and \
                            (course, teacher, day, i) in teacher_time_30min_blocks:
                        teacher_sum_vars.append(teacher_time_30min_blocks[(course, teacher, day, i)])
                opt_model.Add(sum(teacher_sum_vars) <= 1)

solver = cp_model.CpSolver()
solver.parameters.log_search_progress = True
status = solver.Solve(opt_model)
if status == cp_model.OPTIMAL:
    for course in kb['required_courses']:
        for teacher in kb['teacher_course_map'][course]:
            if solver.Value(course_teacher[(course, teacher)]):
                print(f'{course} is taught by {teacher}')
                for timestr in kb['times']:
                    if solver.Value(course_teacher_timestr[(course, teacher, timestr)]):
                        print(f'\tat {timestr}')
                    #else:
                    #    print(f'\tNOT at {timestr}')
else:
    print("No solution found.")