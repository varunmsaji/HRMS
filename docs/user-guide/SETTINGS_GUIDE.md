# Settings Guide

<!-- Generated from apps/web/src/lib/settings-guide/content.json by `npm run guide:docs`. Edit the JSON, not this file. -->

What each setting is, what every option does, and how to use it, in plain English.

## Contents

- [How the settings fit together](#how-the-settings-fit-together)
- **Organisation**
  - [Company Profile](#company-profile)
  - [Companies (Legal Entities)](#companies)
  - [Branches](#branches)
  - [Departments](#departments)
  - [Designations](#designations)
  - [Grades](#grades)
- **Attendance & Time**
  - [Shifts](#shifts)
  - [Attendance Periods](#attendance-periods)
  - [Work Calendars](#work-calendars)
  - [Holiday Calendars](#holiday-calendars)
  - [Weekly-Off Patterns](#weekly-off-patterns)
  - [Attendance Policies](#attendance-policies)
  - [Workplace Geofences](#attendance-geofences)
  - [Overtime Policies](#overtime-policies)
  - [Regularization Policies](#regularization-policies)
- **Leave**
  - [Leave Types](#leave-types)
  - [Leave Policies](#leave-policies)
  - [Leave Combination Rules](#leave-combination-rules)
  - [Leave Year](#leave-year-setting)
  - [Statutory Minimums](#statutory-leave-minimums)
- **Policies**
  - [Policy Assignments](#policy-assignments)
  - [Policy Resolution](#policy-resolution)
- **Payroll**
  - [Salary Components](#salary-components)
  - [Salary Structures](#salary-structures)
  - [Statutory Rates](#statutory-rates)
- **Administration**
  - [Setup](#setup)
  - [Users](#users)

## How the settings fit together

Think of the settings as three layers. First you describe your company and its calendar: who works where, when, and which days are holidays. Next you write the rulebooks: how attendance is judged, how overtime is paid, how leave is earned and used. Last, you tell the system which people follow which rulebook.

A rulebook does nothing until it is published and assigned to people. Most of the confusion in a new set-up comes from skipping one of those two steps, so this guide repeats the point wherever it matters.

### A sensible order to set things up

1. Set up your organisation: the Company Profile first (country, currency, timezone, working days), then the company's legal registrations, branches, departments, designations and grades (all in the Organisation group of Settings).
2. Create your Shifts and publish each shift's schedule.
3. Create Holiday Calendars, a Weekly-Off Pattern, and then a Work Calendar that combines them.
4. Create an Attendance Policy, an Overtime Policy and a Regularization Policy, and publish each.
5. Create your Leave Types, then a Leave Policy for each, then publish them. Set the Leave Year first, and add Statutory Minimums if the law in your state requires them.
6. Open Policy Assignments and assign one policy of each kind to the whole Company. This is the safety net so that nobody is left without rules.
7. Add narrower assignments only where a group is different, such as one department or one grade.
8. Use Policy Resolution to check a few real employees and confirm they get what you expect.
9. At the end of each month, use Attendance Periods to check and lock the month before payroll.
10. Before the first pay run, create any extra Salary Components, check the Salary Structures, and verify the Statutory Rates (Payroll group).
11. Invite your team under Users and give each person the lowest role that lets them do their job.

### Words used throughout

- **Draft and publish**: Shifts and all policies are saved as a draft first. A draft is a working copy that nobody is affected by. When you publish it with an effective date it becomes the rule people actually follow. Older versions are kept as history.
- **Effective date**: The date a published version starts to apply. Days before it keep following the older version, so changing a policy never rewrites the past.
- **Scope**: The group a policy is assigned to: the whole company, a branch, a department, a grade, a designation, a shift, or one employee.
- **Most specific wins**: If someone belongs to several groups that each have a policy, the smallest, most specific group wins. The order from strongest to weakest is employee, shift, designation, grade, department, branch, legal entity, company.

# Organisation

<a id="company-profile"></a>
## Company Profile

The one record that describes your business as a whole: its name, country, currency, timezone, working week and branding. Almost every other part of the system reads from it.

**When to use it:** Fill it in first, right after signing up, and come back when something about the business changes. The Setup page tracks whether it is complete.

### Identity

- **Company name:** Required, up to 200 characters. The everyday name shown around the product.
- **Legal name:** The registered name, if it differs from the everyday name.
- **Registration number:** Your company registration number, up to 64 characters.
- **Industry code:** A short label for your industry, up to 40 characters.
- **Company size:** One of 1-10, 11-50, 51-200, 201-500, 501-1000 or 1000+. Anything else is rejected.

### Region and money

- **Country code:** Two letters, such as IN. Saved in capitals.
- **Currency:** Three letters, such as INR. It can only be changed while the company is on its trial. After the trial it is locked, because changing currency would reinterpret every amount already recorded.
- **Timezone:** The company's default timezone. Only timezones on the allowed list are accepted. Every date and time the system works out (punches, late marks, shifts) uses this clock unless a branch or shift overrides it. It cannot be changed once any attendance has been calculated for the company, because that would reinterpret hours that payroll may already depend on.

### Contact and address

- **Email, phone, website:** Company contact details. The email must be a valid address.
- **Address lines 1 and 2, city, state, postal code, country code:** The head-office address. Used for display and documents, not for any rule.

### Localisation

- **Language code:** The company's language, for example en.
- **Date format:** How dates are written across the product, for example dd/MM/yyyy.
- **Fiscal year start:** The month your financial year begins. April is the default for India. Reports and year-based settings that follow the financial year start from this month.

### Working schedule and hours

- **Working days:** Tick the days that are normal working days, Monday to Sunday. At least one must be ticked. This is the company-wide default week; Work Calendars and Weekly-Off Patterns refine it for particular groups.
- **Business hours start and end:** In 24-hour HH:mm, for example 09:00 and 18:00. The end must be later than the start. These describe the office day in general. They are not a shift and do not decide who is late.

### Branding

- **Logo URL:** A link to your logo image, up to 2048 characters.
- **Primary colour:** A colour code such as #4F46E5, used for the company theme.

**Example:** A Bengaluru company sets country IN, currency INR, timezone Asia/Kolkata, fiscal year April, working days Monday to Saturday, and business hours 09:30 to 18:30.

**Good to know**

- Check the timezone and currency before you add employees or run attendance. They become locked once real data depends on them.
- A suspended company is read-only: no changes can be saved until it is reactivated.
- If two people edit at once, the second save is refused and shows the latest version so nothing is silently overwritten.
- Every change is written to the audit log with who made it and what it was before.

<a id="companies"></a>
## Companies (Legal Entities)

A legal entity is the registered company that actually employs people and files returns. It carries the tax and statutory registrations that appear on payslips and compliance reports.

**When to use it:** Add one when you set up, and another only if your group has separately registered companies. The first release allows one company per account, with any number of branches under it.

### Basic details

- **Company name:** Required, up to 200 characters. The legally registered name.
- **Registered address:** The registered office address, up to 4000 characters.

### Statutory registrations

All optional, but payroll and compliance documents need the ones that apply to you.

- **PAN:** Ten characters: five letters, four digits, one letter, such as ABCDE1234F. Checked for format.
- **GSTIN:** Fifteen characters in the official GST format, such as 29ABCDE1234F1Z5. Checked for format.
- **TAN:** The tax deduction account number, used for TDS returns.
- **CIN:** The corporate identification number.
- **PF establishment code:** Your provident fund registration.
- **ESI code:** Your employee state insurance registration.
- **Labour welfare fund (LWF) registration:** Your LWF registration, where your state requires one.

### Authorised signatory

- **Signatory name and designation:** The person who signs documents on the company's behalf, such as offer letters.
- **Signature image URL:** A link to an image of the signature, for documents that carry one.

### Active or inactive

- **Deactivate:** Hides the company from new use. It is refused while the company still has active branches. Nothing is ever hard-deleted.

**Example:** Acme Pvt Ltd is added with its PAN, GSTIN, TAN and PF code. Pay runs are then created per legal entity, so the right registrations print on every payslip.

**Good to know**

- A pay run belongs to one legal entity, so every employee must sit under the right one.
- Fix a wrong PAN or GSTIN here rather than on documents; the format check will catch most typing errors.
- To deactivate a company, move or deactivate its branches first.

<a id="branches"></a>
## Branches

A branch is a physical office or site. It holds the address, an optional timezone, and the map position and radius that attendance geofencing uses.

**When to use it:** Add each location where people work. Add the map coordinates and radius if you want punches checked against the office location.

### Details

- **Company:** The legal entity the branch operates under. Required.
- **Branch name:** Required, up to 200 characters.
- **Address lines 1 and 2, city:** The branch address.
- **State / union territory:** Chosen from the official list of Indian states and union territories.
- **PIN code:** Six digits and cannot start with 0, such as 560001.
- **Timezone:** Optional. Leave it empty and the branch uses the company timezone. Set it only for a site in a different zone. Like the company timezone, it cannot be changed once attendance has been calculated for people at that branch.

### Geofence

These three work together. Leave them empty to have no location check at this branch.

- **Latitude:** Between -90 and 90, for example 12.9716.
- **Longitude:** Between -180 and 180, for example 77.5946.
- **Geofence radius (m):** A whole number of metres from 1 to 100,000, for example 200. A punch counts as on site when it is inside this circle.

### Active or inactive

- **Deactivate:** Refused while the branch has active departments, active employees, or employees authorised to punch there. Move or remove those first; nothing is moved automatically.

**Example:** The Pune office is added with its address, latitude and longitude, and a radius of 150 m. Staff who punch from home or the car park outside the circle are flagged.

**Good to know**

- Open the office on a map, copy the coordinates of the entrance, and add a little extra radius for GPS drift. Too small a radius causes honest staff to be flagged.
- Workplace Geofences (under Attendance & Time) decides what happens when a punch is outside the circle.
- Branch timezone is the middle step in the order shift, then branch, then company.

<a id="departments"></a>
## Departments

Departments are the teams in your company. They can nest inside each other, can belong to a branch, and can have a head, who becomes an approver for their people.

**When to use it:** Build the team structure before you add employees, and keep it current as teams change.

### Details

- **Department name:** Required, up to 150 characters.
- **Branch:** Optional. Ties the department to a location.
- **Parent department:** Optional. Makes this a sub-team of another. The chain can be at most 5 levels deep, and a department cannot be placed under itself or one of its own sub-teams.
- **Department head:** Optional. Must be an existing employee. The head acts as the department-head stage in leave, overtime and regularization approvals.

### Active or inactive

- **Deactivate:** Refused while active employees are assigned to the department; reassign them first.

**Example:** Engineering is the parent of Backend and Frontend. Priya is set as head of Backend, so requests that need a department-head decision for her team reach her.

**Good to know**

- The department code is generated for you; you do not type it.
- Departments can be used as the scope of a policy assignment, so a sensible structure makes policies easier to target.
- If an approval seems to skip a step, check that the department has a head set.

<a id="designations"></a>
## Designations

A designation is a job title, such as Software Engineer or HR Executive. It can be linked to a department and a grade.

**When to use it:** Create the titles you use, then pick one for each employee.

### Details

- **Designation title:** Required, up to 150 characters.
- **Department:** Optional. Links the title to one department.
- **Grade:** Optional. Links the title to a level. Setting it needs only the permission to manage designations, not grades.

### Active or inactive

- **Deactivate:** Refused while active employees hold the title; reassign them first.

**Example:** Senior Accountant is linked to the Finance department and to grade G4.

**Good to know**

- The designation code is generated for you.
- Designations can be the scope of a policy assignment, for example a different overtime rule for Drivers.
- Keep titles consistent; reports group by designation.

<a id="grades"></a>
## Grades

A grade is a level or pay band. It records the pay range, notice and probation lengths and the approval limit that apply to people at that level.

**When to use it:** Create grades if you manage people by level. They are optional, but they let you describe each level once.

### Details

Every field except the name is optional.

- **Grade name:** Required, up to 100 characters.
- **Level:** A whole number used to order grades, from 0 up.
- **Min CTC and Max CTC (₹):** The annual pay range for the grade. The minimum may not be greater than the maximum.
- **Approval limit (₹):** The amount this grade is allowed to approve.
- **Notice period (days):** Whole days, 0 to 3650.
- **Probation (days):** Whole days, 0 to 3650.

### Active or inactive

- **Deactivate:** Refused while active employees are on the grade; reassign them first.

**Example:** G3 is level 3 with CTC from ₹6,00,000 to ₹9,00,000, a 60-day notice period and a 90-day probation.

**Good to know**

- The grade code is generated and cannot be duplicated.
- At present the pay range, notice, probation and approval limit are recorded for reference. Other parts of the system do not yet enforce them, so they will not block a salary outside the range.
- Grades can be the scope of a policy assignment, for example one leave policy for managers and another for trainees.

# Attendance & Time

<a id="shifts"></a>
## Shifts

A shift is a working-hours schedule, such as 9 am to 6 pm or a flexible 8-hour day. It tells the system when an employee is expected to be at work, so that lateness, early leaving and overtime can be worked out.

**When to use it:** Set up shifts before attendance policies, because attendance is always judged against an employee's shift. Create one shift for each different working pattern you run, such as General, Morning, Night and Flexible.

### The shift itself

Every shift has a name and one or more versions of its schedule.

- **Shift name:** What people will see, for example "General Shift". The system creates the shift code for you.
- **Active / inactive:** A shift you no longer use can be deactivated. Existing history is kept.

### The schedule (each version)

Each shift can have many schedule versions over time, but only one is live on any date.

- **Type: Fixed:** Everyone starts and ends at set times, for example 09:00 to 18:00. Lateness and early leaving are measured against these times.
- **Type: Flexible:** People can arrive any time inside a window, as long as they put in the required hours. You set the earliest start and latest end of the window, plus the number of required minutes.
- **Core hours (flexible shifts):** An optional block of the day when everyone must be present, for example 11:00 to 15:00, even though start and end times are flexible. The attendance policy decides what happens if someone misses core hours.
- **Effective from:** The date this version of the schedule starts. A schedule must have one to be published.
- **Timezone:** Leave it blank to use the branch's timezone, or the company's if the branch has none. Set it only if this shift runs on a different clock, such as a remote team.
- **Scheduled, minimum and maximum minutes:** The planned length of the working day and the allowed range. These are for information and reports only. They are not used to judge attendance.

### Flags

- **Night shift:** Marks the shift as a night shift. The overtime policy can use this to treat overtime on this shift as night overtime.
- **Overtime eligible:** People on this shift can earn overtime. If this is off, no overtime is detected for them under policies that rely on the shift.
- **Operates on holidays:** The shift works on public holidays, so employees are expected to be present and are not treated as having the day off.
- **Operates on weekly-off days:** The same idea for weekly rest days, for shifts that run seven days a week.
- **Shift-specific weekly-off pattern:** Normally an employee's weekly off comes from their work calendar. Choose a pattern here if people on this shift have a different weekly off, such as a rotating crew.

### Breaks

Breaks are optional. Add them if you want unpaid breaks to reduce worked hours, or want to flag people who take too long.

- **Name:** For example Lunch or Tea.
- **Kind: fixed window:** The break happens at a set time, such as 13:00 to 14:00.
- **Kind: flexible duration:** People can take the break at any time inside a window, but only for a minimum and maximum number of minutes.
- **Paid:** A paid break counts as working time. An unpaid break is taken out of the hours worked.
- **Mandatory:** The break is expected every day.
- **Allows split:** The break can be taken in more than one piece, for example two short tea breaks instead of one long one.

**Example:** A General Shift is Fixed, 09:00 to 18:00, with a one-hour unpaid lunch from 13:00 to 14:00. It is marked overtime eligible. A Night Shift is Fixed, 21:00 to 06:00, with the Night shift flag turned on.

**Good to know**

- Opening a shift and clicking Edit shows the name and the whole schedule together. Save keeps it as a draft.
- Nothing changes for employees until you publish the draft from the Versions tab and give it an effective date.
- To change a live schedule, edit it and publish again with a future effective date. The old version stays as history.

<a id="attendance-periods"></a>
## Attendance Periods

An attendance period is a stretch of dates, usually a month, that you formally close once attendance for it is final. Closing it locks the month so nothing can be changed after payroll has used the numbers.

**When to use it:** Use this at the end of each month, before running payroll. It is the point where you confirm that every exception is sorted out.

### Creating a period

- **Company:** Which company (legal entity) the period belongs to. Each company runs its own cycle.
- **Cycle: calendar month:** Pick a month and the period covers the first to the last day of it.
- **Cycle: custom date range:** Choose your own start and end dates, for example the 26th of one month to the 25th of the next.
- **Label:** A name such as "October 2026". It is filled in for you for calendar months.

### What you can do with a period

- **Validate:** Checks whether the period is ready to close. It lists anything still blocking it, with a count for each.
- **Finalize and lock:** Closes the period. After this, punches, roster changes, regularization requests and overtime approvals for those dates are refused until the period is reopened.
- **Reopen:** Unlocks a closed period when a correction is genuinely needed. A reason is required, and only people with the unlock permission can do it.

### What can block a period from closing

- **Missing attendance:** Some employees have no calculated attendance for the period.
- **Configuration errors:** Some days could not be calculated because a policy or shift is missing.
- **Incomplete attendance:** Days that still need someone to resolve them by hand, such as a missing punch. Depending on the attendance policy, these may instead be automatically treated as absent or present when you lock.
- **Pending regularization requests:** Correction requests that nobody has approved or rejected yet.
- **Pending overtime approvals:** Overtime waiting for a decision.
- **Unpublished roster entries:** Roster rows still in draft.
- **Mismatched days:** Days where paid, unpaid and loss-of-pay shares do not add up to exactly one day.
- **Work on approved leave:** Punches on a day of approved full-day leave, waiting for an HR decision.

**Example:** On 1 November you create the October period. You press Validate and it shows 6 pending regularization requests. You get them decided, validate again, then Finalize and lock. Payroll can now rely on October.

**Good to know**

- Validate as often as you like. It changes nothing.
- Lock only when you are sure. Reopening is possible but is meant for real corrections, and it is recorded.

<a id="work-calendars"></a>
## Work Calendars

A work calendar answers one question for every date: is it a working day, a holiday, a weekly off or a shutdown? It does this by combining your holiday calendars, a weekly-off pattern and special dated exceptions.

**When to use it:** Create at least one work calendar for the whole company. Create more if different locations or teams have different holidays or weekly offs.

### What goes into a work calendar

- **Name and description:** For identification, for example "Kerala Office Calendar".
- **Holiday calendars:** One or more holiday calendars whose dates count as holidays.
- **Weekly-off pattern:** The rule for weekly rest days, such as every Sunday or the 2nd and 4th Saturday.
- **Dated exceptions:** One-off changes to a specific date, described below.

### Exception types

Each exception has a date, a type, and an optional name and reason.

- **Special working day:** A day that would normally be off but is a working day this time, for example a Saturday worked to make up for a bridge holiday.
- **Shutdown:** A day or days the whole company is closed, which is not a regular holiday.
- **Substitute holiday:** A holiday moved to another date, for example when a festival falls on a Sunday.
- **Cancel holiday:** Removes a holiday from the calendar for that year.

### The setup helper

- **Work calendar setup:** A guided page that suggests a normal working week, shows you the result as a calendar, and lets you activate it. This is the quickest way to create your first calendar.
- **Impact preview:** Before a calendar change is saved, the system shows which days and which employees would be affected. Read it before confirming.

**Example:** The Kerala Office Calendar uses the India National and Kerala Office holiday calendars, with every Sunday and the 2nd Saturday off. A special working day is added for the Saturday that makes up for a bridge holiday.

**Good to know**

- A work calendar only affects people once it is assigned in Policy Assignments.
- Changing a calendar can change past or future attendance results, which is why the impact preview exists.

<a id="holiday-calendars"></a>
## Holiday Calendars

A holiday calendar is a reusable list of holiday dates, such as India National, Kerala Office or Company FY26.

**When to use it:** Make a separate calendar for each group of holidays that applies to a different set of people, then combine them in work calendars.

### Settings

- **Calendar name:** For example "India National Holidays".
- **Kind: national:** Holidays observed across the country.
- **Kind: regional:** Holidays for one state. A state code, such as KL or MH, is required.
- **Kind: company:** Holidays only your company observes.
- **Kind: location:** Holidays for one office or location.
- **Valid from and valid to:** The dates within which the calendar applies. Holidays outside this range are ignored. Leave them empty for no limit.
- **Holidays:** The individual dates and their names. A month view lets you click a day to add a holiday.

**Example:** You create "Kerala Office FY26", set it to regional with state code KL, valid from 1 April 2026 to 31 March 2027, then add Onam, Vishu and the other dates.

**Good to know**

- Splitting national, state and company holidays into separate calendars means you update each only once a year.
- A holiday calendar does nothing alone. It must be included in a work calendar.

<a id="weekly-off-patterns"></a>
## Weekly-Off Patterns

A weekly-off pattern is the rule for which days of the week people rest, such as every Sunday, alternate Saturdays, or the 2nd and 4th Saturday.

**When to use it:** Create one pattern for each different rest-day arrangement in your company, then attach it to a work calendar or a shift.

### Pattern kinds

- **Fixed weekdays:** The same weekday or weekdays every week, for example Saturday and Sunday.
- **Nth weekday of the month:** A particular occurrence, such as the 2nd and 4th Saturday of every month.
- **Alternate weeks:** Every other week, such as alternate Saturdays.
- **Custom:** Several rules in one pattern, where each rule can use an occurrence (such as 2nd Saturday), an alternating week, or both.

### What each rule asks for

- **Weekday:** Monday to Sunday.
- **Occurrence:** For nth-weekday rules: 1st, 2nd, 3rd, 4th, 5th or last.
- **Starting from and off week:** For alternate rules: which week the pattern starts from, and whether the off week is the same as the starting week or the opposite one.
- **Off amount:** A full day off, or a half day. Half-day offs are handled as a day where people work half.

**Example:** "Sunday plus 2nd and 4th Saturday" is a custom pattern with two rules: every Sunday as a full day, and the 2nd and 4th Saturday as full days.

**Good to know**

- Attach the pattern to a work calendar so the calendar knows the weekly offs.
- Use a shift-specific pattern only for people whose rest days really differ from the company calendar.

<a id="attendance-policies"></a>
## Attendance Policies

An attendance policy is the rulebook for turning raw punches into a day's result: present, half-day, absent, or incomplete. It also decides how lateness, early leaving, missing punches and location checks are treated.

**When to use it:** Create at least one general policy for the whole company. Add stricter or looser ones for groups that need them, such as factory staff or senior managers.

### Grace

- **Grace in (minutes):** How late someone can arrive without being counted late. With 10 minutes of grace, arriving at 9:08 for a 9:00 shift is not late. Arriving at 9:25 is 15 minutes late.
- **Grace out (minutes):** The same idea for leaving early.
- **Earliest punch-in before shift start:** How early an employee may punch in on their own. Earlier punches from the app are refused. Early time is recorded but does not count as work or overtime. Leave blank for no limit.

### Missing punch and missing shift

- **Missing punch behaviour:** What happens when a punch in or out is missing. Incomplete (the default) flags the day for someone to fix. Absent marks the day absent straight away. Require regularization leaves the day waiting for a correction request.
- **Missing shift behaviour:** What happens when the system cannot work out the employee's shift and there are no punches. Incomplete flags the day. Absent marks it absent. If the employee did punch, the day is judged on the punches alone, without lateness or early leaving.

### Multiple punches

- **Multi-punch mode: pair all:** Counts only the time between each in and out pair. Gaps in between, such as a long lunch out, are not counted.
- **Multi-punch mode: first in, last out:** Counts the whole span from the first in to the last out, gaps included.
- **Duplicate punch window (seconds):** Two punches of the same kind within this many seconds count as one. This absorbs double taps. The default is 60.

### Flexible and split shifts

- **Core-hours breach behaviour:** For flexible shifts with core hours. Ignore does nothing. Flag marks the day for reports. Half-day or Absent changes the day's result when someone misses core hours.
- **Split shift: missed block behaviour:** What to do when someone has no punch in one of a split shift's blocks: ignore it, make it a half-day, make it absent, or require regularization.

### On-duty

- **On-duty requires punch:** When off, an approved on-duty day, such as field work, counts as fully paid without any punches, and any punches on it earn no overtime. When on, the punches still decide the status, overtime included, and the day is only flagged.

### Breaks, caps and lock behaviour

- **Lates to half-day (per month):** Every time the late days in a month reach a multiple of this number, that day becomes a half-day. For example, with 3 the 3rd, 6th and 9th late days are half-days. Blank turns it off.
- **Excess-break days to half-day (per month):** The same rule for days where breaks ran too long. With 3, the 3rd, 6th and 9th such days are half-days.
- **Incomplete at lock time:** What happens to days still incomplete when the attendance period is closed. Treat as absent makes them unpaid. Treat as present makes them paid. Keep incomplete refuses to close the period until someone resolves them.
- **Early departure requires approval:** Leaving early beyond grace without an approved request is given the harshest early-departure band instead of a graduated one.

### Location check (geofencing)

This applies only to employees punching from the mobile app. Corrections by HR are never location-checked. A phone's location can be faked, so a pass is evidence, not proof.

- **Location check:** Disabled does not look at location. Optional records and flags it but never blocks a punch. Required blocks self-service punches made outside an approved workplace.
- **Worst acceptable GPS accuracy (metres):** Location readings less precise than this are refused. The allowed range is 5 to 500 and the default is 100.
- **Oldest acceptable reading (seconds):** Location readings older than this are refused, so an old stored location cannot be reused. The allowed range is 5 to 300 and the default is 60.

### Bands

When several rules apply on the same day, the harshest result wins: absent, then half-day, then the hour-band result.

- **Hour bands:** A table that turns hours worked into a day result. For example, under 4 hours is absent, 4 to 8 hours is half-day, and 8 hours or more is present. At least one band is needed to publish, and bands must not overlap.
- **Late bands:** A table that turns minutes late, after grace, into a result: none, late, half-day or absent. Optional.
- **Early departure bands:** The same idea for minutes of leaving early. Optional.

**Example:** The General policy gives 10 minutes grace, treats a missing punch as incomplete, counts every third late day in a month as a half-day, and uses hour bands of under 4 hours absent, 4 to 8 half-day, 8 or more present.

**Good to know**

- Open a policy and click Edit. You see the name and every setting at once. Save stores it as a draft.
- A policy only takes effect after you publish the draft with an effective date and assign it in Policy Assignments.
- Start location checks on Optional to see what Required would block before you switch it on.

<a id="attendance-geofences"></a>
## Workplace Geofences

Workplace geofences define the approved places employees may punch from. A workplace is a branch that has map coordinates and a radius. The location check itself is switched on inside each Attendance Policy.

**When to use it:** Use this if you want to know, or enforce, that employees punch from the office or site rather than from anywhere.

### Workplaces

- **Workplace list:** Shows each branch with its coordinates and radius. A branch with no coordinates or radius cannot be used.
- **Edit coordinates and radius:** Opens the branch so you can set its latitude, longitude and radius in metres. Employees within the radius count as at the workplace.

### Extra workplaces for individual employees

- **Employee and workplace:** Employees can always punch at the branch on their assignment. Use this to let a person work legitimately at other approved locations too. Employees cannot choose a workplace themselves.
- **Authorise:** Saves the extra permission.

### Location attempts

Attempts appear here only once a policy with Optional or Required location checks is in use.

- **Attempt list:** A record of location-checked punches, with how far from the workplace each one was and whether it was accepted. A switch shows only the rejected ones.

**Example:** Your Kochi office has coordinates and a 150 metre radius. With a Required policy, staff there can punch in only within that radius. A sales executive who also visits the Bangalore office is authorised for that workplace too.

**Good to know**

- A phone's reported location can be spoofed, so treat results as evidence rather than proof.
- Make the radius big enough to cover the whole building and car park, or honest employees will be rejected.

<a id="overtime-policies"></a>
## Overtime Policies

An overtime policy decides who can earn overtime, how much is counted, who must approve it, and whether it is paid or turned into time off.

**When to use it:** Create one if any of your people work beyond their shift and you need that time recognised or paid. Leave it unassigned for staff who never earn overtime.

### Who earns overtime

- **Eligibility:** Whether overtime depends on the shift's overtime flag, applies to everyone, applies to no one, or depends on grade.
- **Minimum overtime (minutes):** Extra time shorter than this is ignored. For example, a 30-minute minimum means 20 extra minutes earn nothing.

### How it is counted

- **Rounding:** Rounds the overtime minutes, for example to the nearest 15 minutes, up or down.
- **Daily, weekly and monthly caps:** The most overtime counted per day, week and month. Anything above the cap is not counted. Blank means no cap.

### Approval

- **Needs approval before:** Overtime must be approved in advance.
- **Needs approval after:** Overtime is approved after it has been worked. This is on by default.
- **Approval chain:** Who approves: nobody, the manager, the manager then HR, or HR.

### Time off instead of pay (comp-off)

Comp-off means compensatory off: a day off given in return for extra work. It only works if a leave type is marked as the company's comp-off type.

- **Comp-off instead of pay:** Approved overtime is turned into compensatory-off days instead of being paid.
- **Comp-off expiry (days):** How long an earned comp-off day can be used before it lapses.
- **Comp-off day length (minutes):** How many overtime minutes make one comp-off day.

### Night overtime

- **Night overtime mode:** Whether overtime counts as night overtime because the shift is a night shift, because it falls in a time window, or either.
- **Night window start and end:** The hours that count as night, for example 22:00 to 06:00. Both must be given together.

### Rate rows

Each day class can appear once. If there is no night row, night overtime uses the normal row's label. If a day class has no row at all, the overtime has no label.

- **Day class:** The kind of day the overtime was worked on: normal, weekly off, holiday or night.
- **Classification code:** A label you choose, such as OT_HOLIDAY, stamped on the overtime. Payroll uses it to decide how that overtime is paid.
- **Multiplier:** A number such as 1.5 or 2. It is for information only. The system never turns it into money.

**Example:** Eligible staff earn overtime after a 30-minute minimum, rounded to 15 minutes, capped at 4 hours a day. The manager approves afterwards. Normal days are labelled OT_NORMAL at 1.5, weekly offs OT_WEEKOFF at 2, and holidays OT_HOLIDAY at 2.5.

**Good to know**

- Open a policy and click Edit to set everything together, then publish from the Versions tab.
- Add at least normal, weekly-off and holiday rate rows. Without them payroll cannot tell what kind of overtime it is.

<a id="regularization-policies"></a>
## Regularization Policies

Regularization means correcting an attendance record after the day has passed, for example when someone forgot to punch out. A regularization policy sets who may ask for a correction, how far back, and who approves it.

**When to use it:** Create one so that corrections follow clear rules rather than ad-hoc requests.

### Who can ask

- **Employee, manager and HR requests:** Choose which of these can raise a correction. Managers and HR can raise one on behalf of someone else.

### Limits

- **Maximum backdated days:** How many days back a correction can reach. Blank means no limit.
- **Maximum requests per month:** How many corrections one person can raise per month. Blank means no limit.

### Evidence

- **Reason required:** The requester must explain. On by default.
- **Attachment required:** The requester must upload a document or proof. Off by default.

### Approval

- **Approval chain:** Automatic, manager, manager then HR, or HR.
- **Auto-approve within (minutes):** You can enter a number here and it is saved, but it is not applied yet. Corrections currently follow the approval chain above. Do not rely on this to approve anything automatically.
- **Blocked when locked:** Refuses corrections for a day that has been individually locked. On by default. Separately, once an attendance period has been closed and locked in Attendance Periods, corrections for those dates are always refused, whatever this setting says.

### Allowed types of correction

Only the types you tick can be requested under this policy.

- **Missing punch:** A punch in or out is absent.
- **Wrong punch:** A punch exists but at the wrong time.
- **Wrong shift:** The day was judged against the wrong shift.
- **Wrong status:** The day's result, such as absent, is wrong.
- **Work from home:** The employee worked from home that day.
- **On duty:** The employee was on official work away from the office.
- **Excess break:** The employee disputes an excess-break flag.
- **Full day:** A whole day should be treated as worked.

**Example:** Employees and managers may raise corrections up to 7 days back, at most 5 a month, with a reason required, and the manager approves each one.

**Good to know**

- Pair this with the attendance policy's missing-punch setting. Choosing Require regularization there leaves days waiting for a request under this policy.
- Click Edit on the policy to set all of this together, then publish from the Versions tab.

# Leave

<a id="leave-types"></a>
## Leave Types

A leave type is a kind of leave, such as Casual Leave, Sick Leave, Earned Leave or Loss of Pay. It is the category itself. The detailed rules for it live in a leave policy.

**When to use it:** Create one for every kind of leave your company offers before creating any leave policy.

### Fields

- **Code:** A short unique label such as CL or SL, up to 30 characters. It cannot be changed afterwards.
- **Name:** What people see, such as Casual Leave.
- **Paid by default:** Whether the leave is paid. Off for types like Loss of Pay.
- **Requires a balance:** On means employees must have days in a balance, which accrue and are checked when applying. Off means there is no balance, as with Loss of Pay.
- **Company's comp-off type:** Marks this as the leave type that holds compensatory-off days. Only one active type can be marked. Approved overtime that is set to give comp-off credits this type automatically.
- **Statutory category:** Earned, Sick, Casual, Maternity or Paternity, or none. If set, leave policies of this type are checked against the legal minimum you set in Statutory Minimums.
- **Active:** Turn it off to stop using the type for new things.

**Example:** Casual (CL), Sick (SL) and Earned (EL) are paid, need a balance, and have statutory categories. Loss of Pay (LOP) is unpaid with no balance. Comp Off (CO) is paid with a balance and is marked as the comp-off type.

**Good to know**

- Paid by default, Requires a balance and Comp-off cannot be changed once the type has been used, because that would change what old records mean.
- Leave types are only categories. Add a Leave Policy to give each one its rules.

<a id="leave-policies"></a>
## Leave Policies

A leave policy holds the rules for one leave type: who can apply, how leave is earned, what happens at year end, and so on.

**When to use it:** Create one for each leave type, publish it, and assign it in Policy Assignments.

### Who can apply

- **Employee self-service:** Employees can apply for themselves.
- **Manager on behalf of a report:** A manager can apply for a team member.
- **HR on behalf of anyone:** HR can apply for any employee.

### Application rules

- **Maximum backdated days:** How far back an application may start. Blank means no limit.
- **Maximum requests per month:** A cap on applications per person per month.
- **Reason required:** The employee must give a reason.
- **Attachment required:** The employee must upload a document, such as a medical certificate.
- **Half-day allowed:** Employees can apply for half a day.
- **Approval chain:** Automatic, manager, manager then HR, manager then head of department then HR, or HR.

### Special handling

- **Sandwich rule:** A weekend or holiday between two leave days counts as leave too. Leave on Friday and Monday also uses Saturday and Sunday.
- **Reserve balance on submission:** A pending application already blocks that part of the balance, so someone cannot apply twice for the same days before the first is approved.
- **Allowed during probation:** Turn off to stop employees on probation applying.
- **Accrue during probation:** Turn off to skip earning leave while on probation. In a month the employee is confirmed, the days up to the probation end date earn nothing; confirming records that date if it is empty.

### Earning leave (accrual)

- **Frequency:** None (no automatic earning), monthly or yearly.
- **Rate per cycle:** Days added each cycle. For example, 1.5 days monthly gives 18 days a year.

### At the end of the leave year

- **What happens to unused leave:** Carry forward up to a cap with the rest lost, lose all of it, or carry forward up to a cap and pay out the rest. If leave from a year that has already closed is cancelled, the same rule applies to the days given back: days over the cap are lost, or paid out in the current month's payroll.
- **Maximum carry-forward days:** The cap. It is required for the pay-out option and blank means unlimited for the others.

### Negative balance

- **Allow negative balance:** Employees can borrow leave they have not earned yet.
- **Days below zero allowed:** How far the balance can go below zero. For example, 3 lets it reach minus 3. The shortfall is recovered when the employee leaves.

### Encashment (paying out leave)

- **Encashment allowed:** Employees can convert leave days to pay.
- **Maximum encashment days:** The most days per request. Enforced.
- **Minimum balance after encashment:** The balance that must stay behind. Enforced.
- **Frequency and calculation basis:** Notes for payroll only. They are not enforced, and leave never works out the money.

### Maternity split (information only)

- **Pre-delivery and post-delivery days:** Records how the entitlement is divided. It is never checked against an application's dates.

**Example:** Casual Leave: manager approval, reason required, 1 day earned monthly, balance does not carry forward. Earned Leave: manager then HR, 1.25 days monthly, carry forward up to 30 days, encashment allowed.

**Good to know**

- If the leave type has a statutory category, the policy cannot be published below the legal minimum you set.
- Open a policy and click Edit to set the name and all rules together, then publish from the Versions tab.

<a id="leave-combination-rules"></a>
## Leave Combination Rules

These rules say whether an employee may have two different kinds of leave applied for on overlapping dates, for example Casual plus Sick.

**When to use it:** Use it only where a pair of leave types should be blocked. By default every pair is allowed.

### Fields

- **Leave type and Combined with:** The two leave types the rule is about.
- **Allowed:** Ticked means the two can overlap. Unticked means blocked.
- **Reason:** An optional note shown to HR on the rule list.

**Example:** A rule blocks Casual with Sick so that someone cannot claim both on the same day. Annual with Casual is left alone, so it stays allowed.

**Good to know**

- If there is no rule for a pair, it is allowed.
- You can add an explicit "allowed" rule for clarity, but it changes nothing.

<a id="leave-year-setting"></a>
## Leave Year

The leave year is the 12-month period that leave balances, yearly earning and carry-forward run against. There is one setting for the whole company.

**When to use it:** Set it once when you start, before leave policies go live. Changing it later affects how balances are counted.

### Choices

- **Calendar year:** The year runs from 1 January to 31 December.
- **Financial year:** The year runs from 1 April to 31 March, as in India.
- **Anniversary:** Each employee's year starts on the date they joined, so everyone's year is different.
- **Custom:** You choose the start month and day. Month 1 is January and 12 is December.

**Example:** A company that reports on the Indian financial year picks Financial year, so balances reset and carry forward on 1 April.

**Good to know**

- Pick the same year you use for payroll and reports to avoid confusion at year end.

<a id="statutory-leave-minimums"></a>
## Statutory Minimums

This is where you record the minimum leave the law requires. A leave policy cannot be published below the strictest minimum set here for its leave type's category.

**When to use it:** Use it if your state or industry sets legal minimums for leave. No figures are filled in for you, so enter the ones that apply to you.

### Fields

- **Leave category:** Earned, Sick, Casual, Maternity or Paternity.
- **Minimum days per year:** The legal floor for that category.
- **State:** Optional. Leave blank if the minimum applies regardless of state.
- **Establishment type:** Optional, for example Shop and Establishment, Factory or IT/ITES.
- **Note:** Optional, such as where the figure comes from.

**Example:** You add Casual leave, 12 days a year for the Shops and Establishments Act in your state. A casual leave policy giving 10 days is refused at publish time.

**Good to know**

- Until a minimum is added for a category, publishing policies in that category is not restricted.
- If several minimums apply, the strictest one is used.

# Policies

<a id="policy-assignments"></a>
## Policy Assignments

Policy assignments connect policies to people. A policy does nothing until it is assigned. You assign a policy to a group, called a scope, and everyone in the group follows it.

**When to use it:** Use it after publishing policies. Start with one policy of each kind for the whole company, then add narrower assignments for groups that differ.

### Scope: who it applies to

Anything other than Company asks you to pick which one.

- **Company:** Everyone.
- **Legal entity:** One registered company within a group.
- **Branch:** One office or location.
- **Department:** For example Sales or Production.
- **Grade:** For example Senior or Manager.
- **Designation:** A job title.
- **Shift:** People working a particular shift.
- **Employee:** One person, for an exception.

### What can be assigned

- **Work calendar and weekly-off pattern:** These show an impact preview before they are saved.
- **Attendance, overtime and regularization policies:** One of each kind per group.
- **Leave policies:** One for each leave type, per group.

### The New Assignment form

- **Scope and target:** Chosen once at the top.
- **Effective from:** The date the assignment starts applying.
- **Policies to assign:** One dropdown per kind, and one per leave type for leave policies. Leave a row on No change to skip it. You can fill in several rows and create them together.
- **Reason:** An optional note for your records.

**Example:** You assign General Attendance to the whole company, then Factory Attendance to the Production department. Ravi in Accounts follows General. Priya in Production follows Factory, because the department is more specific than the company.

**Good to know**

- A group follows only one policy of each kind. A new assignment closes the old one from its effective date and keeps it as history.
- A policy must be published to take effect. A draft is not enough.
- Always keep a company-wide assignment of each kind as a safety net.

<a id="policy-resolution"></a>
## Policy Resolution

Policy Resolution is a checking tool. It tells you which policy an employee follows on a given date and which group it came from.

**When to use it:** Use it after changing assignments, or whenever someone asks why they were treated a certain way.

### How to use it

The result names the policy and the level that matched, such as Department: Production.

- **Employee:** Who you are checking.
- **Date:** The day you are checking.
- **Policy kind:** Which type of policy to look up.

### What the result can mean

- **A policy is shown:** That is the one in force for that employee on that date.
- **Config incomplete:** No policy of that kind is assigned to any group the employee belongs to, or the assigned policy has no published version for that date. The system never falls back to a made-up default. Fix it by assigning a policy at company level and publishing it.

**Example:** You check Priya's attendance policy for 15 November. It shows Factory Attendance from the Production department, so you know the assignment is working.

**Good to know**

- Checking changes nothing. It is safe to use at any time.

# Payroll

<a id="salary-components"></a>
## Salary Components

A salary component is one building block of pay, such as Basic, HRA or a Conveyance allowance. Structures are made by combining components.

**When to use it:** Add a component whenever you pay or charge something that is not already listed, before you use it in a structure.

### Details

- **Code:** Capital letters, digits and underscores only, up to 30 characters, such as CONVEYANCE. It cannot be changed later. Codes the pay run writes itself (for example OVERTIME, ROUNDING, PF_EMPLOYEE, TDS_EMPLOYEE) and codes starting with ARR_ are reserved and refused.
- **Name:** Required. What appears on the payslip.
- **Type:** Earning is money paid to the employee. Employer contribution is a cost to the company that sits inside CTC. Deduction is money taken from pay.
- **Display order:** A number from 0 to 10,000. Lower numbers appear first on the payslip.

### Flags

Each decides how the component is treated in the pay run.

- **Taxable:** Counts toward income tax (TDS) calculations.
- **Counts as PF wage:** Included in the wages on which provident fund is calculated. Basic is, by default.
- **Counts as ESI wage:** Included in the wages on which ESI is calculated.
- **Prorated by paid days:** Reduced in proportion when the employee is paid for fewer days than the month.
- **Shown on payslip:** Whether the line is printed on the payslip.

### Ready-made components

- **System components:** Basic, House Rent Allowance, Special Allowance, and the employer PF and ESI contributions are created automatically. You can change their flags and names, but not their type.

**Example:** You add CONVEYANCE as a taxable earning, prorated, shown on the payslip, with display order 40.

**Good to know**

- Deduction components can be defined but are not placed in structures yet. PF, ESI, professional tax, LWF and TDS are worked out automatically from Statutory Rates.
- Turn a component off with the active switch rather than deleting it; payslips already issued keep their lines.
- Getting the PF and ESI wage flags right matters, because they decide the statutory amounts for every employee.

<a id="salary-structures"></a>
## Salary Structures

A salary structure is a recipe that turns an employee's yearly CTC into monthly pay lines. It lists components and how each is calculated.

**When to use it:** Create a structure for each pay pattern, such as Standard or Metro. Standard and Standard (metro) are provided to start from.

### The structure

- **Code:** Capital letters, digits and underscores, up to 30 characters.
- **Name:** Required.
- **Description:** Optional, up to 2000 characters.

### Lines (one per component, up to 50)

Each component may appear only once.

- **Calculation: fixed amount:** A set monthly amount.
- **Calculation: % of monthly CTC:** A percentage of the monthly CTC.
- **Calculation: % of gross:** A percentage of gross pay. Allowed on earnings only.
- **Calculation: % of another component:** A percentage of another earning in the same structure, such as HRA as 40% of Basic. No circular references.
- **Calculation: balance of gross:** Takes whatever is left. Every structure needs exactly one, and it must be an earning. Special Allowance is usually this line.
- **Percentage:** 0 to 100, up to four decimal places.
- **Monthly cap (₹):** An upper limit on the line. Not available on the balancing line.
- **Applies when:** Always, only if PF applies, or only if ESI applies. A line that does not apply to an employee is skipped for them.

### Versions and publishing

- **Draft:** Edit lines freely. Nobody is paid from a draft. Editing a published structure creates a new draft copied from the current version.
- **Publish with an effective-from date:** The version becomes the live one from that date, and the previous version ends the day before. A published version can no longer be edited.
- **Preview:** Enter an annual CTC and whether PF or ESI applies to see the monthly breakup before you publish or assign.

**Example:** In the Standard structure Basic is 50% of gross, HRA is 40% of Basic, employer PF is 12% of Basic, and Special Allowance balances the rest, so the lines always add up to the CTC.

**Good to know**

- CTC is the total cost: gross pay plus employer contributions. Gross is found by working backwards so the lines add up exactly.
- If the CTC is too small for the fixed amounts, the preview shows an error instead of a wrong figure.
- Publish a new version with a future date to change pay next month without touching past months.

<a id="statutory-rates"></a>
## Statutory Rates

The government rates that pay runs use for provident fund, ESI, professional tax, labour welfare fund and income tax. They are data, not code, so you can update them when the law changes.

**When to use it:** Review them before your first pay run, and again whenever a notification changes a rate.

### What every rate has

- **Scheme:** PF, ESI, PT (professional tax), LWF or TDS.
- **State code:** Required for PT and LWF, and not allowed for PF, ESI or TDS.
- **Effective from:** The date the rate starts. Adding a new rate ends the open one for the same scheme and state the day before.
- **Notes:** Where the figure came from, such as the notification or circular.

### PF fields

- **Employee and employer contribution (%):** The two shares of PF wages.
- **Of which pension, EPS (%):** The part of the employer share that goes to pension. It cannot exceed the employer share.
- **Wage ceiling (₹):** PF is normally worked out on wages up to this amount.
- **EDLI (%) and Admin charges (%):** The insurance and administration charges.
- **No pension from age:** From this age the pension part is not paid.

### ESI fields

- **Employee and employer contribution (%):** The two shares.
- **Wage ceiling (₹):** Above this gross, ESI cover does not apply, and the run shows a warning.
- **No employee share up to a daily wage of (₹):** Low-paid staff pay no employee share, but the employer share is still due.

### PT and LWF

- **Slabs:** A band of monthly gross (from and to) with the amount due. PT slabs can apply to one gender and can have a different amount in a named month. No slabs means the state levies no PT.
- **LWF months:** The month numbers in which LWF is deducted, such as 6 and 12, with employee and employer amounts per slab.

### TDS (income tax, new regime)

- **Standard deduction (₹/year):** Taken off annual income before tax.
- **Full rebate at or below taxable income (₹/year):** Nobody at or below this pays tax.
- **Health and education cess (%):** Added to the tax.
- **Warn above (₹/year):** Surcharge is not calculated. Income above this only raises a warning.
- **Slabs:** Annual income bands and the percentage on each.

### Verification

- **Verified:** Each rate must be verified, as a sign-off that it matches the latest notification. A pay run that uses an unverified rate cannot be approved.
- **Editing a rate:** Correcting a rate in place clears its verified status, so it must be checked again. Pay runs already created keep the copy they used.

**Example:** Maharashtra raises a professional tax slab. You add a new PT rate for MH effective 1 April, check the amounts against the notification, and click Verify.

**Good to know**

- Rates that came ready-made are marked not verified until someone checks them.
- Never type a rate from memory. Use the official notification, and put its reference in Notes.
- Money is stored in paise internally, but you always type rupees.

# Administration

<a id="setup"></a>
## Setup

A progress checklist that shows how far the company's initial set-up has got and what to do next.

**When to use it:** Check it after signing up. It is also shown as a welcome prompt when you first arrive.

### What it shows

- **Progress badge:** Setup complete, or the number of steps done out of the total.
- **Next step:** The first unfinished step, with a button that goes straight to the page that finishes it.
- **Step list:** Each step with a done or not-done mark.

### How a step is completed

- **Company Profile:** Currently the only tracked step. It is done once the company profile has been filled in. It is worked out by the system from your data; you cannot tick it by hand.

**Good to know**

- When every step is done the company is marked as onboarded, once.
- This checklist only tracks the profile. The wider order for setting up time, leave and policies is in the overview at the top of this guide.

<a id="users"></a>
## Users

Everyone who can log in to this company, and the role each person holds. A role decides which pages they can use and whose data they can see.

**When to use it:** Use it to invite a new person, or to change what an existing user can do.

### The list

- **Name and email:** The person's login.
- **Status:** Whether the account is active.
- **Roles:** The roles held. A person with no role can sign in but can do nothing.

### Invite a user

- **Email:** Required. Where the invitation is sent. If that email already has an account in this company, the invite is refused.
- **Role:** The role they start with. The invitation link is valid for 7 days, and the person sets their own password when they accept.

### Manage roles

- **Roles you can assign:** Company Admin, HR Admin, Reporting Manager, Branch Manager and Employee. You choose among these five; custom roles cannot be created here.
- **At least one role:** Saving with no roles ticked is refused.
- **Your own roles:** You cannot change your own roles, so you cannot lock yourself out.

### What each role can see

- **Company Admin:** Full access to settings, users and approvals across the whole company.
- **HR Admin:** Runs HR day to day across the company: employees, onboarding, attendance reading, leave administration, calendars and holidays, and preparing payroll. Approving a pay run, and editing shifts, attendance policies, leave types and leave policies, stay with Company Admin.
- **Reporting Manager:** Sees and approves for their own team, including indirect reports.
- **Branch Manager:** Sees employees, attendance and leave balances for their own branch. It does not by itself allow approving requests.
- **Employee:** Sees and acts on their own records: applying for leave, viewing their balance and attendance.

**Example:** A new HR executive is invited as HR Admin. A manager promoted to run the Pune office is given Branch Manager as well as Employee.

**Good to know**

- Give the least access that does the job. Most people only need Employee.
- Invite someone from their employee record if they should be linked to it, so their own data and their team's data are found correctly.
- Role changes and invites are written to the audit log.
