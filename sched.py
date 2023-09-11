from ortools.sat.python import cp_model
import pandas as pd
import re
import json

with open("inputs.json") as f:
    kb = json.load(f)

teachers = set()
for course in kb['required_courses']:
    for teacher in kb['teacher_course_map'][course]:
        teachers.add(teacher)

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

def run(enforce_teacher_num_courses=True, enforce_room=True, enforce_room_occupied=True):
    opt_model = cp_model.CpModel()

    teacher_time_30min_blocks = {}
    course_teacher = {}
    course_teacher_timestr = {}

    for course in kb['required_courses']:
        for teacher in kb['teacher_course_map'][course]:
            course_teacher[(course, teacher)] = opt_model.NewBoolVar(f'{course}_{teacher}')

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
                    for i in range(parsed['start_30min_block'], parsed['end_30min_block']+1):
                        for room in kb['rooms']:
                            teacher_time_30min_blocks[(course, teacher, day, i)] = opt_model.NewBoolVar(f'{course}_{teacher}_{day}_{i}')
                            opt_model.AddImplication(course_teacher_timestr[(course, teacher, timestr)],
                                                     teacher_time_30min_blocks[(course, teacher, day, i)])

    course_rooms = {}
    if enforce_room:
        # each course and time of day must have a room
        for course in kb['required_courses']:
            if course not in kb['noroom']:
                course_rooms[course] = {}
                for room in kb['rooms']:
                        course_rooms[course][room] = opt_model.NewBoolVar(f'{course}_{room}')
                opt_model.Add(sum(course_rooms[course].values()) == 1)

    if enforce_room and enforce_room_occupied:
        # each room has only a single course in it for every 30min block
        for room in kb['rooms']:
            for timestr in kb['times']:
                parsed = parse_time(timestr)
                for day in parsed['days']:
                    for i in range(parsed['start_30min_block'], parsed['end_30min_block']+1):
                        room_sum_vars = []
                        for course in kb['required_courses']:
                            if course not in kb['noroom']:
                                for teacher in kb['teacher_course_map'][course]:
                                    if (course, teacher, day, i) in teacher_time_30min_blocks:
                                        course_room_time = opt_model.NewBoolVar(f'{course}_{room}_{day}_{i}')
                                        opt_model.Add(course_room_time == teacher_time_30min_blocks[(course, teacher, day, i)]).OnlyEnforceIf(course_rooms[course][room])
                                        room_sum_vars.append(course_room_time)
                        opt_model.Add(sum(room_sum_vars) <= 1)

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
    for teacher in teachers:
        for timestr in kb['times']:
            parsed = parse_time(timestr)
            for day in parsed['days']:
                for i in range(parsed['start_30min_block'], parsed['end_30min_block']+1):
                    teacher_sum_vars = []
                    for course in kb['required_courses']:
                        if teacher in kb['teacher_course_map'][course] and \
                                (course, teacher, day, i) in teacher_time_30min_blocks:
                            teacher_sum_vars.append(teacher_time_30min_blocks[(course, teacher, day, i)])
                    opt_model.Add(sum(teacher_sum_vars) <= 1)

    if enforce_teacher_num_courses:
        # each teacher must have specified number of courses
        for teacher in teachers:
            teacher_vars = []
            for course in kb['required_courses']:
                if teacher in kb['teacher_course_map'][course]:
                    teacher_vars.append(course_teacher[(course, teacher)])
            opt_model.Add(sum(teacher_vars) == kb['teacher_num_courses'][teacher])

    solver = cp_model.CpSolver()
    solver.parameters.log_search_progress = True
    status = solver.Solve(opt_model)
    if status == cp_model.OPTIMAL:
        result = []
        for course in kb['required_courses']:
            for teacher in kb['teacher_course_map'][course]:
                if solver.Value(course_teacher[(course, teacher)]):
                    for timestr in kb['times']:
                        if solver.Value(course_teacher_timestr[(course, teacher, timestr)]):
                            if enforce_room:
                                if course not in kb['noroom']:
                                    for room in kb['rooms']:
                                        if solver.Value(course_rooms[course][room]):
                                            result.append({'course': course, 'teacher': teacher, 'room': room, 'time': timestr})
                                else:
                                    result.append({'course': course, 'teacher': teacher, 'time': timestr})
                            else:
                                result.append({'course': course, 'teacher': teacher, 'time': timestr})
        return result
    else:
        print("No solution found.")

result = run(True, True, True)
result_df = pd.DataFrame(result)
print(result_df)
result_df.to_excel('output.xlsx', index=False)