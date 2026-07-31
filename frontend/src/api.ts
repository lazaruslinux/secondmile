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

// The journey. Distances here are Miles, the world's own unit: converted from
// real distance by the server at a rate per activity, and never shown in
// kilometers, because the map is measured in them.

export interface MileBucket {
  earned: number
  spent: number
  available: number
}

// Either standing at a place or somewhere along a road. The road fields are
// null in the first case and the location fields in the second.
export interface JourneyPosition {
  location_id: string | null
  location_name: string | null
  road_id: string | null
  road_name: string | null
  position_mi: number
  // Measured from the road's from_id end, which is the direction the map draws
  // it, so it can be handed straight to getPointAtLength.
  fraction: number | null
  road_length_mi: number | null
  road_from_id: string | null
  road_to_id: string | null
  heading_to_id: string | null
  heading_to_name: string | null
}

export interface JourneyPlace {
  id: string
  name: string
  reachable: boolean
}

export interface JourneyRoad {
  id: string
  name: string
  from_id: string
  to_id: string
  length_mi: number
  region_id: string | null
  open: boolean
}

export interface JourneyRegion {
  id: string
  name: string
  detail: string
  unlocked: boolean
  cost_run_miles: number
}

export interface JourneyState {
  started_at: string
  updated_at: string
  position: JourneyPosition
  destination: { id: string; name: string } | null
  buckets: Record<Activity, MileBucket>
  total_traveled_mi: number
  unopened_chests: number
  unseen_events: number
  locations: JourneyPlace[]
  roads: JourneyRoad[]
  regions: JourneyRegion[]
}

export type JourneyEventType = 'travel' | 'chest' | 'milestone' | 'arrival' | 'unlock'

// One loose shape for every event type rather than a union, because the server
// stores this as free JSON and a field it stops sending should read as absent
// rather than break the type. Which fields are present follows from the type.
export interface JourneyEventData {
  activity?: Activity
  raw_distance_mi?: number
  miles?: number
  road_id?: string
  road_name?: string
  toward_name?: string
  location_name?: string
  local?: boolean
  chest_id?: number
  set_name?: string
  area_name?: string
  source?: string
  name?: string
  detail?: string
  mile?: number
  was_destination?: boolean
  region_name?: string
  cost_run_miles?: number
}

export interface JourneyEvent {
  id: number
  type: JourneyEventType
  created_at: string
  data: JourneyEventData
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

export interface Accolade {
  id: string
  name: string
  detail: string
  earned_at: string
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
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

export function listWorkouts(limit: number): Promise<Workout[]> {
  return getJson<Workout[]>(`/workouts?limit=${limit}`)
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

// Reading the journey is what makes the server walk any workout that arrived
// while the app was closed, so this is never just a read.
export function getJourney(): Promise<JourneyState> {
  return getJson<JourneyState>('/journey')
}

// Answers with the whole state, so a view that just changed the destination
// does not need a second round trip to redraw.
export async function setDestination(locationId: string): Promise<JourneyState> {
  const res = await sendJson('/journey/destination', 'POST', { location_id: locationId })
  return (await res.json()) as JourneyState
}

export function getRecap(): Promise<JourneyEvent[]> {
  return getJson<JourneyEvent[]>('/journey/recap')
}

export async function ackRecap(): Promise<void> {
  await send('/journey/recap/ack', { method: 'POST' })
}

export async function unlockRegion(regionId: string): Promise<JourneyState> {
  const res = await send(`/regions/${encodeURIComponent(regionId)}/unlock`, { method: 'POST' })
  return (await res.json()) as JourneyState
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

export function getAccolades(): Promise<Accolade[]> {
  return getJson<Accolade[]>('/accolades')
}
