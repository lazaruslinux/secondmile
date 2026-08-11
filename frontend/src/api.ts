// Every call to the server lives here, so the shape of the API is written down
// in exactly one place and the views never touch fetch() themselves.

const BASE = '/api'

export type Units = 'imperial' | 'metric'
// The three things an account may keep back from its friends. Everything else
// a friend sees is not optional, and pace is deliberately not on the list: it
// is distance over time, and both of those stay on every card.
export type HiddenField = 'avg_hr' | 'active_kcal' | 'route'
export type Activity = 'walk' | 'run' | 'cycle' | 'swim'
// Where a workout came from. Nothing writes 'manual' any more, and history
// full of it stays readable: a card that cannot name where a row came from
// would be rewriting the past rather than describing it.
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
  // What this account keeps back from its friends. Empty until somebody turns
  // a switch on, and absent from a server that predates the field.
  hidden_from_friends?: HiddenField[]
  is_admin: boolean
}

export interface Status {
  name: string
  version: string
  // Whether the sign-up form should ask for an invite code.
  registration_open: boolean
  // The IANA zone the instance groups days and weeks in, which is the zone
  // every time on screen is read in. Optional: a server that predates the
  // field leaves the app on the browser's own zone.
  timezone?: string
}

// Soft flags: the server imports the workout either way and marks what looked
// wrong, so a bad sync never silently becomes progress.
export interface WorkoutFlags {
  impossible_pace?: boolean
  daily_cap?: boolean
}

// One row of your own history: the feed's row with the flags added. The log
// draws the same card the feed does, so the two are one shape and the log is
// served the feed's row. The flags are the only thing on top, because they are
// said to the person whose numbers they are and to nobody else.
export interface Workout extends FeedItem {
  flags: WorkoutFlags
}

// One row of the Log's Deleted section. Not a card and not a feed row: a
// deleted workout's pictures, video and route answer 404 to everybody, so
// there is nothing here to draw beyond what it was and how long is left to
// change your mind.
export interface DeletedWorkout {
  workout_id: number
  activity: Activity
  start_ts: string
  distance_mi: number
  duration_s: number
  title: string | null
  deleted_at: string
  // Counted by the server, from the same window the restore endpoint checks,
  // so the number on screen and the answer to pressing Restore agree.
  days_left: number
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
  // The server also sends the medals they chose to show. Nothing reads them
  // here: the feed said them beside the name and they read as things this
  // workout earned, so they are the profile's job now, one tap away.
}

// What a workout has been given, from everyone, plus whether this account is one
// of them. Bodies are not here: words go to the person they were written for.
export interface Encouragement {
  cheers: number
  notes: number
  cheered_by_me: boolean
}

// One event in the feed: this account's workouts and its friends' together.
// A friend's row carries what they did in full unless they have said otherwise
// in their own settings, and a field they keep back is not here at all rather
// than here and blank.
export interface FeedItem {
  workout_id: number
  user: Person
  activity: Activity
  start_ts: string
  distance_mi: number
  duration_s: number
  // Absent when the person whose workout it is hides them. Null on a row that
  // simply never carried a heart rate, which is a different thing.
  avg_hr?: number | null
  active_kcal?: number | null
  // The medals this workout earned, read the same way as a workout's own.
  medals?: string[]
  // False as well when the owner keeps their routes to themselves, so no map
  // is drawn and nothing is asked for.
  has_route: boolean
  source: Source
  own: boolean
  // Own rows only. What the workout was worth, in converted miles.
  xp?: number
  // What the person wrote on it and the pictures and video they put with it.
  // Friends' rows carry them too: a post is something deliberately shared. All
  // of them are optional, the same way they are on a workout.
  title?: string | null
  post?: string | null
  photos?: number[]
  // At most one, and a list all the same, because that is the shape the server
  // counts media in and one shape is easier to read than two.
  videos?: number[]
  encouragement: Encouragement
}

// One invite this account sent, which is a name somebody typed and nothing
// more. Deliberately not a Person: whether that name belongs to anybody is not
// something the server will say, because answering would make the invite form a
// way to look people up.
export interface SentInvite {
  username: string
}

// Mutual only: a friendship exists when one side asked and the other agreed.
// Counts appear nowhere, here or anywhere else.
export interface Friends {
  friends: Person[]
  pending_in: Person[]
  pending_out: SentInvite[]
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
  // Absent on a friend's totals when they have hidden their calories, which is
  // the server leaving the figure out rather than sending a zero.
  active_kcal?: number
  workouts: number
}

// The three kinds of medal. Every medal in the catalogue belongs to exactly
// one. Nothing on screen groups by them any more; the server still says which.
export type MedalFamily = 'race' | 'weekly' | 'time'

// One medal and how many times it has been earned. The server sends all eleven
// whether they have been earned or not, so a count of zero is a medal still to
// come rather than a missing row. Medals repeat: the count is the whole of what
// an account holds, and the stars around the artwork are worked out from it
// here rather than sent.
export interface Medal {
  id: string
  family: MedalFamily
  name: string
  count: number
  first_earned_at: string | null
  last_earned_at: string | null
}

// One earning of one medal, which is what the recap lists: the same medal
// earned twice arrives as two entries. Every field but the id is optional, so
// an entry that carries nothing else still reads.
export interface MedalEarn {
  id: string
  name?: string
  earned_at?: string
}

// The parts of a profile a person types in themselves. All optional, all
// clearable: a null is how a field is emptied rather than left alone.
export interface ProfileDetails {
  first_name: string | null
  last_name: string | null
  // ISO date, yyyy-mm-dd, which is what the native date input reads and writes.
  birthdate: string | null
  gender: string | null
  // A line or two about themselves, at most 200 characters. Null clears it.
  bio: string | null
}

// How much of one item an account has spent and how much of it was spent on
// them. Counts only: the server sends no names and no dates with these.
export interface ItemTally {
  used?: number
  received?: number
}

// The two items that can be given away. Seeds stay out: a seed is planted in
// your own plot and never crosses a fence.
export interface ItemTallies {
  oil?: ItemTally
  water?: ItemTally
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
  // What they wrote about themselves, and the one field here a friend reads
  // too. Optional, like the rest of it.
  bio?: string | null
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
  // The medals shown in the slots under the picture, as ids, at most three. Any
  // owned medal may be in them.
  displayed_badges: string[]
  // The whole catalogue with its counts, in catalogue order. Optional so the
  // app still renders against a server that predates the field.
  medals?: Medal[]
  // The sports shown as diamonds, at most three. The server sends the effective
  // list, which is the player's own pick or its best guess when they have not
  // made one. Optional so the app still renders against a server that predates
  // the field, in which case the view picks the top three itself.
  diamond_sports?: Activity[]
  // Consecutive weeks with at least one workout, counting back from this one.
  streak_weeks?: number
  // Which days of the current week already carry a workout, Monday first. Seven
  // booleans, bucketed by the server in the instance's timezone, so they agree
  // with the streak beside them. Optional so the app still renders against a
  // server that predates the field, which simply draws no days.
  week_days?: boolean[]
  // Activities with nothing recorded are absent rather than zeroed, the same
  // way the weekly totals behave.
  week: Partial<Record<Activity, ActivityStats>>
  lifetime: Partial<Record<Activity, ActivityStats>>
  // What the plot has come to. seeds_found counts the distinct species owned,
  // out of the twelve a chest can hold; plant_levels is every level on every
  // plant added up. Optional so the app still renders against a server that
  // predates the grove.
  grove?: { seeds_found: number; plant_levels: number }
  // Oil and water, spent and arrived. Optional like the grove above it.
  item_tallies?: ItemTallies
  // The next chest and how far off it is, if the server says. Both shapes a
  // server might reasonably use are allowed for, and the bar is left out
  // entirely when neither is there.
  next_chest?: {
    tier?: string | null
    tier_id?: string | null
    miles_away?: number
    mi_away?: number
    // The friend whose oil lifts this chest a step when it drops. Null when
    // nothing is waiting and also when this step has no room to be lifted,
    // which is why a waiting gift and a named one are two different questions.
    gifted_by?: string | null
  }
  next_chest_tier?: string | null
  next_chest_mi?: number
  // Oil spent on this account and not yet landed on a chest. Optional: a server
  // that predates gifts says nothing, which reads as none.
  pending_gifts?: { from: string }[]
}

// Somebody else, as a deliberate tap on one person is allowed to see them.
// Friends only, and nothing private travels in it: no email, no birthdate, no
// age, no gender, no chests, no inventory. Everything but the name and the
// picture is optional, because this screen is opened casually and a field that
// is not there has to draw as nothing rather than take the app down.
export interface FriendProfile {
  user_id: number
  username: string
  display_name?: string | null
  has_avatar: boolean
  // The server's own word for which picture this is, appended to its address so
  // a new one is seen straight away. A string here rather than the number the
  // own profile carries, and only ever pasted onto a URL.
  avatar_version?: string | null
  created_at?: string
  border_tier?: number
  flourish?: number
  displayed_badges?: string[]
  level?: number
  // The ladder as the You screen draws it: the total, how far into the current
  // level they are, and how long that level is. The meter is filled from the
  // last two, and there is no meter without them.
  xp?: number
  xp_into_level?: number
  xp_for_next_level?: number
  // What they wrote about themselves, shown under their name.
  bio?: string | null
  // Raw lifetime distance, the same number the You screen leads with: what
  // their body covered. Never the weighted number the game counts as XP.
  miles?: number
  medals?: Medal[]
  // The summary only. The plot itself comes from the grove endpoint.
  grove?: { seeds_found?: number; plant_levels?: number }
  // The same four counts the You screen carries. Nobody is named in them, so
  // they cross the fence whole.
  item_tallies?: ItemTallies
  // The same two sets of totals the You screen carries, in the same shape, so
  // the sport chips and the two cards are drawn by the same components. A
  // calorie figure is missing from these where they have hidden it.
  week?: Partial<Record<Activity, ActivityStats>>
  lifetime?: Partial<Record<Activity, ActivityStats>>
  // The last few pictures they attached to a workout, newest first.
  recent_photos?: RecentPhoto[]
  // Their latest activities in the feed's own row shape, newest first, so what
  // a card may show cannot drift between here and the feed.
  workouts?: FeedItem[]
}

// One picture on the strip across a profile, with what the tag under it says.
// The picture itself is fetched from the workout photo endpoint, which is gated
// on the same friendship the profile is.
export interface RecentPhoto {
  photo_id: number
  workout_id: number
  activity: Activity
  distance_mi: number
  duration_s: number
}

export interface AvatarState {
  has_avatar: boolean
  avatar_version: number
}

// Seeds carry a rarity that decides how big the thing they grow into gets, and
// they roll no higher than rare. The two steps above that belong to the tools:
// a wish is epic and oil is legendary. The special one is its own kind of rare
// and never rolls.
export type Rarity = 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary' | 'special'

// What a chest holds. Every item is a tool with exactly one thing to do with it:
// a seed is planted, water is poured onto a planting, oil is given to a friend,
// and a wish is spent on any seed the grove is still missing.
export type ItemKind = 'seed' | 'water' | 'oil' | 'wish'

// One unused thing in the satchel. Only a seed carries a species; the tools
// never do.
export interface SatchelItem {
  id: number
  kind: ItemKind
  species: string | null
  // What the species is called on screen, where the server sends one plain
  // name rather than the two below. Null for every tool.
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

// The catalogue of what a seed can be. It is asked for rather than written down
// here because a wish is spent on a species nobody owns yet, so no list of what
// is held can answer what is missing, and two copies of twelve names drift.
export interface SpeciesRow {
  id: string
  seed_name: string
  plant_name: string
  rarity: Rarity
}

export interface SpeciesCatalog {
  species: SpeciesRow[]
  // What an unmarked seed is called. It is not a species and has no row, so the
  // server sends its name alongside the list rather than in it.
  wish_name: string
}

// One thing growing in the plot. growth_mi is in converted miles: the same
// miles the level bar counts, spent here as well.
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
  // Everything levels. level_mi is what one level of this species costs, and
  // level is how many it has, which stops at the last one.
  level: number
  level_mi: number
  // Grown at level one, and finished at the last level, where it is gilded.
  mature: boolean
  gilded: boolean
  // 1 seedling, 2 growing, 3 grown, worked out by the server.
  stage?: number
}

// A friend's plot, which is theirs to grow and only ours to water. Enough to
// draw it and pour onto it: no miles, no dates, nothing to compare against.
export interface FriendPlanting {
  id: number
  species: string
  name?: string
  plant_name?: string | null
  rarity?: Rarity | string
  // How many levels it has put on, which is how a plant is doing and so what
  // somebody over the fence would see anyway.
  level?: number
  // How far through its current level it is, from 0 to 1, and full at the top
  // where there is no next level. It is the bar and nothing more: the miles
  // behind it are the owner's record of their weeks and never cross the fence.
  growth?: number
  // 1 seedling, 2 growing, 3 grown. Read defensively: any of these may be
  // missing, and a plant that is finished takes no more water.
  stage?: number
  mature?: boolean
  gilded?: boolean
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
// the medals were earned before anyone looked; this is the letter, not the
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

// One plant that put a level on since the letter was last read.
export interface RecapGrowth extends Planting {
  levels_gained: number
  // Where the climb started, which is what turns a level into a sentence: a
  // plant that stood at zero came up out of the ground, and one that stood at
  // seven simply grew. Optional, since a plant from before the column was
  // written says nothing about where it began.
  level_before?: number
}

// One chest that landed while the app was shut. Named by the step of the ladder
// that dropped it, and carrying the friend whose oil lifted it when there was
// one. The count and the list of givers are worked out from these here.
export interface RecapChest {
  tier_id?: string | null
  tier?: string | null
  gifted_by?: string | null
}

// One workout that arrived while the app was shut. It was credited and
// published when it landed; the letter lists it so it can be given a name and
// some words after the fact. workout_id rather than id, because that is the key
// the feed and the edit panel already read.
export interface RecapWorkout {
  workout_id: number
  activity: Activity
  start_ts: string
  duration_s: number
  distance_mi: number
  title?: string | null
  post?: string | null
  photos?: number[]
  videos?: number[]
}

export interface RecapState {
  since: string | null
  // Raw miles, per activity: the distance a body actually covered. All four
  // keys arrive, zeros included, and each one is still read as optional so a
  // key that goes missing reads as none rather than throwing.
  miles: Partial<Record<Activity, number>>
  miles_total?: number
  // The weighted number the game runs on. Never called miles anywhere.
  xp?: number
  // Chests are opened in the inventory now, so the letter names what landed
  // rather than carrying it. One entry per chest, duplicates included, so two
  // of the same step are said twice.
  chests?: RecapChest[]
  // When the phone last synced, or null for an account that never has.
  last_sync_at?: string | null
  plant_growth?: RecapGrowth[]
  // Medals earned since the last time this was read, one entry per earning
  // across every family. Optional, and each entry may carry nothing but its id.
  medals?: MedalEarn[]
  // Words and cheers received since the last read. Optional throughout.
  encouragement?: RecapEncouragement
  // The newest workouts that arrived, capped by the server, and how many there
  // really were. The cap is why the count travels: a list of ten out of a
  // hundred and fifty has to say so.
  workouts?: RecapWorkout[]
  workouts_total?: number
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

// Declining an invitation and ending a friendship are the same act to the
// server, and there is one verb for both.
export async function removeFriend(userId: number): Promise<void> {
  await send(`/friends/${userId}`, { method: 'DELETE' })
}

// Taking back an invite you sent, by the name you sent it to. By name rather
// than by id because a name is all the sent list carries: the server never says
// whose id, if anybody's, is behind it. Answers 204 either way.
export async function cancelInvite(username: string): Promise<void> {
  await send(`/friends/invites/${encodeURIComponent(username)}`, { method: 'DELETE' })
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

// One note somebody wrote on a workout, as its owner reads it.
export interface WorkoutNote {
  from: string
  body: string
  created_at: string
}

// The words written on your own workout, oldest first. Owner only: anybody
// else, friends included, is answered the same 404 a workout that does not
// exist gets, because a note is written to the runner rather than to a thread.
export function getWorkoutNotes(workoutId: number): Promise<WorkoutNote[]> {
  return getJson<WorkoutNote[]>(`/workouts/${workoutId}/notes`)
}

export function listWeeks(count: number): Promise<Week[]> {
  return getJson<Week[]>(`/workouts/weeks?count=${count}`)
}

// The parts of a workout the person who did it types in themselves. A field
// left out is left alone; a null empties it. What the body actually covered is
// not here and is not editable anywhere: miles are earned.
export interface WorkoutEdit {
  title?: string | null
  post?: string | null
}

export async function updateWorkout(workoutId: number, edit: WorkoutEdit): Promise<Workout> {
  const res = await sendJson(`/workouts/${workoutId}`, 'PATCH', edit)
  return (await res.json()) as Workout
}

// Takes the workout out of every feed and every total at once. Nothing comes
// back: what changed is the whole account, so whoever called this reloads the
// screen rather than patching one card's worth of it.
export async function deleteWorkout(workoutId: number): Promise<void> {
  await send(`/workouts/${workoutId}`, { method: 'DELETE' })
}

// Puts one back, and answers with the row in the history's own shape so the
// card can be drawn again without asking for the page.
export async function restoreWorkout(workoutId: number): Promise<Workout> {
  const res = await send(`/workouts/${workoutId}/restore`, { method: 'POST' })
  return (await res.json()) as Workout
}

// The Deleted section: your own deleted workouts that can still be got back,
// newest first. Empty once the window has run out on all of them.
export function listDeletedWorkouts(): Promise<DeletedWorkout[]> {
  return getJson<DeletedWorkout[]>('/workouts/deleted')
}

// What the server accepts, checked here as well so an oversized picture is
// answered at once instead of after a whole upload.
export const MAX_PHOTO_BYTES = 10 * 1024 * 1024
export const PHOTO_TOO_LARGE = 'That picture is too large. The limit is 10 MB.'

// One part, named "file", and nothing else in the form, the same as the avatar
// upload. Answers with the id of the picture that was stored.
export async function uploadWorkoutPhoto(workoutId: number, file: File): Promise<number> {
  // Refused here rather than sent and refused, so a picture too big to keep
  // never costs an upload. Thrown as the status the server would have answered
  // with, so callers have one sentence to show either way.
  if (file.size > MAX_PHOTO_BYTES) throw new ApiError(413, PHOTO_TOO_LARGE)
  const body = new FormData()
  body.append('file', file)
  const res = await send(`/workouts/${workoutId}/photos`, { method: 'POST', body })
  const created = (await res.json()) as { id: number }
  return created.id
}

export async function deleteWorkoutPhoto(workoutId: number, photoId: number): Promise<void> {
  await send(`/workouts/${workoutId}/photos/${photoId}`, { method: 'DELETE' })
}

// Read by the owner and by their accepted friends, on the cookie that is
// already there, which is why this is an address rather than a fetch.
export function workoutPhotoUrl(workoutId: number, photoId: number): string {
  return `${BASE}/workouts/${workoutId}/photos/${photoId}`
}

// The video limits, stated here as well so a clip the server would refuse is
// refused before it is uploaded. The length is the server's to judge: reading
// it here would mean decoding the file in the browser first.
export const MAX_VIDEO_BYTES = 100 * 1024 * 1024
export const VIDEO_TOO_LARGE = 'That video is too large. The limit is 100 MB.'

// The photo upload's twin: one part named "file", and the id of what was
// stored comes back. The wait is longer than any other call in this file
// because the server re-encodes the clip before it answers.
export async function uploadWorkoutVideo(workoutId: number, file: File): Promise<number> {
  if (file.size > MAX_VIDEO_BYTES) throw new ApiError(413, VIDEO_TOO_LARGE)
  const body = new FormData()
  body.append('file', file)
  const res = await send(`/workouts/${workoutId}/videos`, { method: 'POST', body })
  const created = (await res.json()) as { id: number }
  return created.id
}

export async function deleteWorkoutVideo(workoutId: number, videoId: number): Promise<void> {
  await send(`/workouts/${workoutId}/videos/${videoId}`, { method: 'DELETE' })
}

// Addresses rather than fetches, for the photo endpoint's reason: both are read
// by an element on the page carrying the session cookie it already has. The
// video answers byte ranges, which is what lets a browser start playing it
// before it holds the whole file.
export function workoutVideoUrl(workoutId: number, videoId: number): string {
  return `${BASE}/workouts/${workoutId}/videos/${videoId}`
}

export function workoutVideoPosterUrl(workoutId: number, videoId: number): string {
  return `${BASE}/workouts/${workoutId}/videos/${videoId}/poster`
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

// The list the server stored, rather than the one just sent to it: it puts the
// fields in its own order and refuses any name it does not know.
export async function setHiddenFromFriends(hidden: HiddenField[]): Promise<HiddenField[]> {
  const res = await sendJson('/settings', 'PATCH', { hidden_from_friends: hidden })
  const body = (await res.json()) as { hidden_from_friends?: HiddenField[] }
  return body.hidden_from_friends ?? []
}

// Reading the profile is what makes the server credit any workout that arrived
// while the app was closed, so this is never just a read.
export function getProfile(): Promise<Profile> {
  return getJson<Profile>('/profile')
}

// A friend's profile. Friends only: anybody else is a 404 that says nothing
// about whether the account exists, which is why there is no way to look
// somebody up anywhere in this app. Self is allowed and answers the same
// friend-shaped view, exactly as the grove endpoint does.
export function getFriendProfile(userId: number): Promise<FriendProfile> {
  return getJson<FriendProfile>(`/profile/${userId}`)
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
export async function uploadAvatar(picture: Blob): Promise<AvatarState> {
  const body = new FormData()
  // Named here rather than taken from whatever was chosen: the picture sent is
  // one this app made, the server derives the stored path from the account, and
  // a filename off somebody's phone has no business in either.
  body.append('file', picture, 'avatar.jpg')
  const res = await send('/profile/avatar', { method: 'POST', body })
  return (await res.json()) as AvatarState
}

export async function deleteAvatar(): Promise<void> {
  await send('/profile/avatar', { method: 'DELETE' })
}

// The version is only ever pasted onto the address, so whichever way a server
// counts it reads the same here: the own profile sends a number and a friend's
// sends a string.
export function avatarUrl(userId: number, version: number | string | null): string {
  return `${BASE}/profile/avatar/${userId}${version === null ? '' : `?v=${version}`}`
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

// The twelve species a chest can roll, in catalogue order. The server is the one
// place they are written down.
export function getSpecies(): Promise<SpeciesCatalog> {
  return getJson<SpeciesCatalog>('/species')
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

// A wish is spent on one species and comes back as that seed, which is what
// takes the wish's place in the satchel. An empty species is the one case where
// there is nothing left to ask for: the server answers with water instead. A
// 4xx means the pick went stale between the list and the tap.
export async function chooseSeed(itemId: number, species: string): Promise<SatchelItem> {
  // Null rather than a missing key, so the "nothing left to ask for" case is
  // said outright rather than left to be inferred from an empty body.
  const res = await sendJson(`/satchel/${itemId}/choose`, 'POST', {
    species: species === '' ? null : species,
  })
  return (await res.json()) as SatchelItem
}
