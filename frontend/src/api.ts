// Every call to the server lives here, so the shape of the API is written down
// in exactly one place and the views never touch fetch() themselves.

const BASE = '/api'

export type Units = 'imperial' | 'metric'
export type Activity = 'walk' | 'run' | 'cycle' | 'swim'
export type Source = 'sync' | 'manual'

export interface Me {
  id: number
  username: string
  units: Units
  is_admin: boolean
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

export async function login(username: string, password: string): Promise<void> {
  await sendJson('/auth/login', 'POST', { username, password })
}

export async function register(
  inviteCode: string,
  username: string,
  password: string,
): Promise<void> {
  await sendJson('/auth/register', 'POST', {
    invite_code: inviteCode,
    username,
    password,
  })
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
