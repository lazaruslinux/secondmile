// Every call to the server lives here, so the shape of the API is written down
// in exactly one place and the views never touch fetch() themselves.

const BASE = '/api'

export type Units = 'imperial' | 'metric'
export type Activity = 'walk' | 'run' | 'cycle' | 'swim'
export type Source = 'sync' | 'manual'

export interface Me {
  id: number
  username: string
  // Null on accounts made from the command line, which never needed an address.
  email: string | null
  email_verified: boolean
  // An address that has been asked for but not yet confirmed from its own
  // inbox. Optional: a server that predates the change simply never sends it.
  pending_email?: string | null
  units: Units
  is_admin: boolean
}

export interface Status {
  name: string
  version: string
  // Whether the sign-up form should ask for an invite code.
  registration_open: boolean
}

// Soft flags: the server imports the workout either way and marks what looked
// wrong, so a bad sync never silently becomes progress.
export interface WorkoutFlags {
  impossible_pace?: boolean
  daily_cap?: boolean
}

export interface Workout {
  id: number
  activity: Activity
  start_ts: string
  duration_s: number
  distance_mi: number
  active_kcal: number | null
  avg_hr: number | null
  source: Source
  flags: WorkoutFlags
  // What this workout was worth, in converted miles. Computed by the server
  // from the same formula the pipeline uses; optional here so the app still
  // renders against a server that predates the field.
  xp?: number
  // The race badge this one run earned, if it earned any. At most one per
  // workout: the longest distance it qualified for.
  race_badge?: string | null
  // Whether the server holds a route for this workout. Optional so the app
  // still renders against a server that predates the field.
  has_route?: boolean
}

// One point of a route, latitude then longitude, as the server sends it.
export type RoutePoint = [number, number]

export interface WorkoutRoute {
  // At most a couple of hundred points. The server trims both ends before
  // storing, so a route never shows where somebody set off from.
  points: RoutePoint[]
}

// Somebody as they appear next to a workout or in a friends list: enough to draw
// them and nothing else. No counts, no totals, nothing to compare against.
export interface Person {
  user_id: number
  username: string
  // The name they go by, "First Last", composed by the server. Null when they
  // have not given one, and absent from a server that predates the field, in
  // which case the username is the only name there is.
  display_name?: string | null
  has_avatar: boolean
  border_tier: number
  // How far the border's growth has come, 0 to 3. Earned by encouraging other
  // people, and the only outward sign of it: the number behind it is never sent.
  flourish: number
}

// What a workout has been given, from everyone, plus whether this account is one
// of them. Bodies are not here: words go to the person they were written for.
export interface Encouragement {
  cheers: number
  notes: number
  cheered_by_me: boolean
}

// One event in the feed: this account's workouts and its friends' together.
// Friends' rows deliberately carry no pace-precision fields and no heart rate;
// distance and time are the whole headline.
export interface FeedItem {
  workout_id: number
  user: Person
  activity: Activity
  start_ts: string
  distance_mi: number
  duration_s: number
  race_badge: string | null
  has_route: boolean
  source: Source
  own: boolean
  // Own rows only. What the workout was worth, in converted miles.
  xp?: number
  encouragement: Encouragement
}

// Mutual only: a friendship exists when one side asked and the other agreed.
// Counts appear nowhere, here or anywhere else.
export interface Friends {
  friends: Person[]
  pending_in: Person[]
  pending_out: Person[]
}

export type EncouragementKind = 'cheer' | 'note'

export interface ActivityTotals {
  distance_mi: number
  active_kcal: number
  workouts: number
}

export interface Week {
  week_start: string
  // Activities with nothing recorded may be absent entirely, so the views read
  // this map defensively rather than assuming four entries.
  activities: Partial<Record<Activity, ActivityTotals>>
  total_active_kcal: number
}

export interface NewWorkout {
  activity: Activity
  start_ts: string
  duration_s: number
  distance_mi: number
  active_kcal?: number
  avg_hr?: number
}

export interface IngestTokenStatus {
  exists: boolean
  rotated_at: string | null
}

// The profile. Distances come back two ways: distance_mi is what the body
// actually covered, and converted_mi is the same distance in Miles, the unit
// the game counts in, which weights the activities against each other.

export interface ActivityStats {
  distance_mi: number
  converted_mi: number
  active_kcal: number
  workouts: number
}

// One race distance and how many times it has been run. The server sends all
// five whether they have been earned or not, so a count of zero is a badge
// still to come rather than a missing row.
export interface RaceBadge {
  id: string
  // Absent from the recap, which is only reporting what arrived rather than
  // what the account holds.
  count?: number
  first_earned_at?: string | null
  last_earned_at?: string | null
}

// The parts of a profile a person types in themselves. All optional, all
// clearable: a null is how a field is emptied rather than left alone.
export interface ProfileDetails {
  first_name: string | null
  last_name: string | null
  // ISO date, yyyy-mm-dd, which is what the native date input reads and writes.
  birthdate: string | null
  gender: string | null
}

export interface Profile {
  user_id: number
  username: string
  // Whatever was typed in, and the "First Last" the server makes of it. Every
  // one of them is optional, so an older server simply shows a username.
  first_name?: string | null
  last_name?: string | null
  display_name?: string | null
  birthdate?: string | null
  gender?: string | null
  // Worked out from the birthdate rather than stored, so the two cannot drift.
  age?: number | null
  created_at: string
  has_avatar: boolean
  // Changes with every upload, and null when there is no picture. Appended to
  // the picture's URL so a new one is seen straight away.
  avatar_version: number | null
  level: number
  // Miles, not points: xp and the two level figures are converted miles, one
  // decimal on screen. The field names are the server's.
  xp: number
  xp_into_level: number
  xp_for_next_level: number
  border_tier: number
  // How far this account's own border growth has come, 0 to 3. Optional: the
  // stage is carried on every person in the feed, so a server that does not put
  // it here as well simply leaves the profile's own frame plain.
  flourish?: number
  // Achievement ids and earned race badge ids together, at most four.
  displayed_badges: string[]
  // All five race distances with their counts. Optional so the app still
  // renders against a server that predates the field.
  race_badges?: RaceBadge[]
  // The sports shown as diamonds, at most three. The server sends the effective
  // list, which is the player's own pick or its best guess when they have not
  // made one. Optional so the app still renders against a server that predates
  // the field, in which case the view picks the top three itself.
  diamond_sports?: Activity[]
  // Consecutive weeks with at least one workout, counting back from this one.
  streak_weeks?: number
  // Activities with nothing recorded are absent rather than zeroed, the same
  // way the weekly totals behave.
  week: Partial<Record<Activity, ActivityStats>>
  lifetime: Partial<Record<Activity, ActivityStats>>
  // How much is in the plot. Optional so the app still renders against a server
  // that predates the grove.
  grove?: { planted: number; mature: number }
  // The next chest and how far off it is, if the server says. Both shapes a
  // server might reasonably use are allowed for, and the line is left out
  // entirely when neither is there.
  next_chest?: { tier?: string | null; miles_away?: number; mi_away?: number }
  next_chest_tier?: string | null
  next_chest_mi?: number
  achievements: { earned: number; total: number }
}

export interface AvatarState {
  has_avatar: boolean
  avatar_version: number
}

export type AchievementKind = 'week-distance'

export interface Achievement {
  id: string
  kind: AchievementKind
  name: string
  detail: string
  // Whether this one has a gilded form at all, which is the weekly ladder only.
  gildable: boolean
  earned: boolean
  gilded: boolean
  earned_at: string | null
}

// Seeds carry a rarity that decides how big the thing they grow into gets. The
// special one is its own kind of rare and never rolls.
export type Rarity = 'common' | 'uncommon' | 'rare' | 'special'

// What a chest holds. Every item is a tool with exactly one thing to do with it:
// a seed is planted, water is poured onto a planting, oil is given to a friend.
export type ItemKind = 'seed' | 'water' | 'oil'

// One unused thing in the satchel. Water and oil carry no species; a seed
// always does.
export interface SatchelItem {
  id: number
  kind: ItemKind
  species: string | null
  // What the species is called on screen, where the server sends one plain
  // name rather than the two below. Null for water and oil.
  name?: string | null
  // A species has two names: what it is called in the hand and what it is
  // called in the ground. A seed says the first one. Both are optional, so a
  // server that sends one name for both is read as it always was.
  seed_name?: string | null
  plant_name?: string | null
  rarity: Rarity
  // The one line a species has to explain about itself, said at the reveal.
  // Null for all but one of them.
  reveal?: string | null
  acquired_at: string
}

// One thing growing in the plot. growth_mi and maturity_mi are converted miles:
// the same miles the level bar counts, spent here as well.
export interface Planting {
  id: number
  species: string
  // The planted form is what a plot is read in. name is the older single-name
  // shape and is only read when plant_name is not there.
  plant_name?: string | null
  seed_name?: string | null
  name?: string | null
  rarity: Rarity
  planted_at: string
  growth_mi: number
  // Zero for anything that levels instead of maturing.
  maturity_mi: number
  mature: boolean
  // A plant that levels counts them from zero and never stops; level_mi is
  // what one of them costs. Null for everything that matures.
  level?: number | null
  level_mi?: number | null
}

// A friend's plot, which is theirs to grow and only ours to water. Enough to
// draw it and pour onto it: no miles, no dates, nothing to compare against.
export interface FriendPlanting {
  id: number
  species: string
  name?: string
  plant_name?: string | null
  // 1 seedling, 2 growing, 3 grown. Read defensively: either field may be
  // missing, and a plant already grown takes no more water.
  stage?: number
  mature?: boolean
}

// What is inside is deliberately not in this response: the reveal belongs to
// opening it.
export interface Chest {
  id: number
  dropped_at: string
  // Which step of the ladder dropped it, "5K" through "Ultra". Chests dropped
  // before the ladder existed carry none, so this is read defensively.
  tier?: string | null
  // A chest a friend's oil brought rather than one the miles earned. Which
  // field names the giver is the server's business; all the shapes it might
  // reasonably use are allowed for here and read in one place.
  bonus?: boolean
  from_username?: string
  giver_username?: string
  giver?: string
  from?: string
}

// Everything that happened while the app was shut. The chests were dropped and
// the badges were earned before anyone looked; this is the letter, not the
// event.
// One note somebody wrote. Read defensively: the sender's name and the words
// are what matter, and every field is optional so a row missing one still
// renders the rest of it.
export interface RecapNote {
  from_username?: string
  username?: string
  from?: string
  body?: string
  created_at?: string
  workout_id?: number
}

// What arrived from other people since the last time the letter was read.
// Cheers may come back as one number or as a row per workout, so both are
// allowed for and the reader adds up whatever it was given.
export interface RecapEncouragement {
  notes?: RecapNote[]
  cheers?: number | { cheers?: number; count?: number; workout_id?: number }[]
  cheer_count?: number
}

export interface RecapState {
  since: string | null
  miles: number
  chests: Chest[]
  achievements: Achievement[]
  // Race badges earned since the last time this was read. Optional, and each
  // entry may carry nothing but its id.
  race_badges?: RaceBadge[]
  // Words and cheers received since the last read. Optional throughout.
  encouragement?: RecapEncouragement
  // Whether the border's growth moved on, and how far it got. Either may be
  // absent; a stage on its own is read as a rise.
  flourish_rose?: boolean
  flourish_stage?: number
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// The one sentence a view shows when a call failed: the server's own words when
// it gave any, and something plain when it did not.
export function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Try again.'
}

// The session can end at any moment (expiry, logout elsewhere, a rotated
// password). Rather than teaching every caller to recognise that, the app
// registers one handler here and gets sent back to the login screen.
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json()
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
    }
  } catch {
    // A response that is not JSON carries nothing worth showing a person.
  }
  return 'Something went wrong. Try again.'
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(BASE + path, { credentials: 'same-origin', ...init })
  if (res.status === 401) unauthorizedHandler?.()
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res
}

async function sendJson(path: string, method: string, body: unknown): Promise<Response> {
  return send(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

async function getJson<T>(path: string): Promise<T> {
  const res = await send(path)
  return (await res.json()) as T
}

export function getMe(): Promise<Me> {
  return getJson<Me>('/auth/me')
}

export function getStatus(): Promise<Status> {
  return getJson<Status>('/status')
}

export async function login(username: string, password: string): Promise<void> {
  await sendJson('/auth/login', 'POST', { username, password })
}

// Returns the server's own wording rather than a copy of it kept here, because
// this answer is deliberately the same whether an account was created or the
// name was already taken, and two places phrasing that differently is how the
// difference leaks back out.
export async function register(
  email: string,
  username: string,
  password: string,
  inviteCode: string,
): Promise<string> {
  const res = await sendJson('/auth/register', 'POST', {
    email,
    username,
    password,
    invite_code: inviteCode,
  })
  const body = (await res.json()) as { detail: string }
  return body.detail
}

export async function verifyEmail(token: string): Promise<void> {
  await sendJson('/auth/verify', 'POST', { token })
}

export async function resendVerification(email: string): Promise<void> {
  await sendJson('/auth/resend-verification', 'POST', { email })
}

export async function logout(): Promise<void> {
  await send('/auth/logout', { method: 'POST' })
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await sendJson('/auth/password', 'POST', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

// The cursor is the start_ts of the last row already shown, and the server
// answers with what started strictly before it. It has to be encoded: an
// unescaped "+00:00" offset arrives as a space and only ever breaks page two.
export function listWorkouts(limit: number, before?: string): Promise<Workout[]> {
  const cursor = before === undefined ? '' : `&before=${encodeURIComponent(before)}`
  return getJson<Workout[]>(`/workouts?limit=${limit}${cursor}`)
}

// The home feed: this account's workouts and its accepted friends', newest
// first. The cursor is the start_ts of the last row already shown, encoded for
// the same reason the history's is.
export function listFeed(before?: string): Promise<FeedItem[]> {
  const cursor = before === undefined ? '' : `?before=${encodeURIComponent(before)}`
  return getJson<FeedItem[]>(`/feed${cursor}`)
}

export function getFriends(): Promise<Friends> {
  return getJson<Friends>('/friends')
}

// Answers the same whether the name belongs to anybody or not, so nothing here
// can be used to find out who has an account.
export async function inviteFriend(username: string): Promise<void> {
  await sendJson('/friends/invite', 'POST', { username })
}

export async function acceptFriend(userId: number): Promise<void> {
  await send(`/friends/${userId}/accept`, { method: 'POST' })
}

// Declining an invitation, taking one back, and ending a friendship are the
// same act to the server, and there is one verb for all three.
export async function removeFriend(userId: number): Promise<void> {
  await send(`/friends/${userId}`, { method: 'DELETE' })
}

// A cheer carries no words and a note carries nothing but the ones typed into
// it. A second cheer on the same workout answers 409, which means it is already
// there rather than that anything went wrong.
export async function encourage(
  workoutId: number,
  kind: EncouragementKind,
  body?: string,
): Promise<void> {
  await sendJson(`/workouts/${workoutId}/encourage`, 'POST', {
    kind,
    ...(body === undefined ? {} : { body }),
  })
}

// This account's workouts and its accepted friends'. A workout with no stored
// route answers 404, which is the ordinary case rather than a failure.
export function getWorkoutRoute(workoutId: number): Promise<WorkoutRoute> {
  return getJson<WorkoutRoute>(`/workouts/${workoutId}/route`)
}

export function listWeeks(count: number): Promise<Week[]> {
  return getJson<Week[]>(`/workouts/weeks?count=${count}`)
}

export async function createWorkout(workout: NewWorkout): Promise<Workout> {
  const res = await sendJson('/workouts', 'POST', workout)
  return (await res.json()) as Workout
}

// Asks for an address to be put on the account, or for the one there to be
// replaced. The current password is the proof it is really this person. The
// answer is the same whatever happened, so nothing here says whether an address
// is already somebody else's.
export async function changeEmail(password: string, email: string): Promise<void> {
  await sendJson('/settings/email', 'POST', { password, email })
}

export function getIngestTokenStatus(): Promise<IngestTokenStatus> {
  return getJson<IngestTokenStatus>('/settings/ingest-token')
}

export async function rotateIngestToken(): Promise<string> {
  const res = await send('/settings/ingest-token/rotate', { method: 'POST' })
  const body = (await res.json()) as { token: string }
  return body.token
}

export async function setUnits(units: Units): Promise<Units> {
  const res = await sendJson('/settings', 'PATCH', { units })
  const body = (await res.json()) as { units: Units }
  return body.units
}

// Reading the profile is what makes the server credit any workout that arrived
// while the app was closed, so this is never just a read.
export function getProfile(): Promise<Profile> {
  return getJson<Profile>('/profile')
}

// Answers with the whole profile, so the slots under the picture can be
// redrawn from the server's word rather than from what was just sent to it.
export async function setDisplayedBadges(badges: string[]): Promise<Profile> {
  const res = await sendJson('/profile', 'PATCH', { displayed_badges: badges })
  return (await res.json()) as Profile
}

// Name, birthdate, and the rest, sent together and answered with the whole
// profile. An empty field goes as a null, which is how the server is told to
// clear it rather than to leave it alone.
export async function setProfileDetails(details: ProfileDetails): Promise<Profile> {
  const res = await sendJson('/profile', 'PATCH', details)
  return (await res.json()) as Profile
}

// The same again for the diamonds. At most three, and the server decides what
// counts as a sport rather than trusting the list it was handed. Null is the
// reset: the server goes back to picking the sports with the most miles behind
// them, which is not the same as an empty list, which means no diamonds at all.
export async function setDiamondSports(sports: Activity[] | null): Promise<Profile> {
  const res = await sendJson('/profile', 'PATCH', { diamond_sports: sports })
  return (await res.json()) as Profile
}

// One part, named "file", and nothing else in the form. The browser writes the
// Content-Type with its own boundary, which is why none is set here.
export async function uploadAvatar(file: File): Promise<AvatarState> {
  const body = new FormData()
  body.append('file', file)
  const res = await send('/profile/avatar', { method: 'POST', body })
  return (await res.json()) as AvatarState
}

export async function deleteAvatar(): Promise<void> {
  await send('/profile/avatar', { method: 'DELETE' })
}

export function avatarUrl(userId: number, version: number | null): string {
  return `${BASE}/profile/avatar/${userId}${version === null ? '' : `?v=${version}`}`
}

export function listAchievements(): Promise<Achievement[]> {
  return getJson<Achievement[]>('/achievements')
}

export function getRecap(): Promise<RecapState> {
  return getJson<RecapState>('/recap')
}

// Marks the letter read. Chests are untouched by this: they wait in the
// profile until they are opened.
export async function ackRecap(): Promise<void> {
  await send('/recap/ack', { method: 'POST' })
}

export function listChests(): Promise<Chest[]> {
  return getJson<Chest[]>('/chests')
}

// Opening one answers with the thing that was inside, which then sits in the
// satchel until it is used.
export async function openChest(chestId: number): Promise<SatchelItem> {
  const res = await send(`/chests/${chestId}/open`, { method: 'POST' })
  return (await res.json()) as SatchelItem
}

// Everything held and not yet used.
export function listSatchel(): Promise<SatchelItem[]> {
  return getJson<SatchelItem[]>('/satchel')
}

// The plot: everything planted, whether it is still growing or done.
export function listGrove(): Promise<Planting[]> {
  return getJson<Planting[]>('/grove')
}

// An accepted friend's plot. Read-only, and the only reason to ask for it is to
// pour water onto something in it.
export function listFriendGrove(userId: number): Promise<FriendPlanting[]> {
  return getJson<FriendPlanting[]>(`/grove/${userId}`)
}

export async function plantSeed(itemId: number): Promise<Planting> {
  const res = await send(`/satchel/${itemId}/plant`, { method: 'POST' })
  return (await res.json()) as Planting
}

// Water goes onto one planting, this account's own or a friend's, chosen by the
// person pouring it.
export async function pourWater(itemId: number, plantingId: number): Promise<void> {
  await sendJson(`/satchel/${itemId}/pour`, 'POST', { planting_id: plantingId })
}

// Oil goes onto a friend and says nothing to them. A 409 means one is already
// waiting on that person.
export async function anointFriend(itemId: number, userId: number): Promise<void> {
  await sendJson(`/satchel/${itemId}/anoint`, 'POST', { user_id: userId })
}
