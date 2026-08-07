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

export interface Profile {
  user_id: number
  username: string
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
  cards: { owned: number; total: number }
  achievements: { earned: number; total: number }
}

export interface AvatarState {
  has_avatar: boolean
  avatar_version: number
}

export type AchievementKind = 'week-distance' | 'collection'

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

export type Rarity = 'common' | 'uncommon' | 'rare'

export interface Card {
  id: string
  set_id: string
  set_name: string
  number: number
  name: string
  rarity: Rarity
  flavor: string
}

// What is inside is deliberately not in this response: the reveal belongs to
// opening it.
export interface Chest {
  id: number
  dropped_at: string
  set_id: string
  set_name: string
}

export interface OpenedChest {
  card: Card
  duplicate: boolean
  count: number
}

// An unowned plate carries its number and rarity and nothing else, so every
// field that would name it is optional here too.
export interface AlbumPlate {
  number: number
  rarity: Rarity
  owned: boolean
  id?: string
  set_id?: string
  set_name?: string
  name?: string
  flavor?: string
  count?: number
  first_found_at?: string
}

export interface AlbumSet {
  id: string
  name: string
  size: number
  owned: number
  cards: AlbumPlate[]
}

export interface Album {
  sets: AlbumSet[]
}

// Everything that happened while the app was shut. The chests were dropped and
// the badges were earned before anyone looked; this is the letter, not the
// event.
export interface RecapState {
  since: string | null
  miles: number
  chests: Chest[]
  achievements: Achievement[]
  // Race badges earned since the last time this was read. Optional, and each
  // entry may carry nothing but its id.
  race_badges?: RaceBadge[]
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

// Own workouts only. A workout with no stored route answers 404, which is the
// ordinary case rather than a failure.
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

export async function openChest(chestId: number): Promise<OpenedChest> {
  const res = await send(`/chests/${chestId}/open`, { method: 'POST' })
  return (await res.json()) as OpenedChest
}

export function getAlbum(): Promise<Album> {
  return getJson<Album>('/album')
}
