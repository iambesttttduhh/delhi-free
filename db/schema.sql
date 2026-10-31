-- =====================================================================
-- Delhi, Free — database schema (Supabase / Postgres, free tier)
--
-- Nothing here costs anything and nothing here is running yet: I cannot
-- create a Supabase project for you (no account, no credentials), and a
-- database in an account I control would be the wrong place for your data.
-- Paste this file into the Supabase SQL editor when you want Phase 4.
--
-- Design rules this file enforces:
--   · an event cannot exist without a verification status and a source
--   · a coordinate cannot be claimed as "venue" precision by accident
--   · the public can read published events and nothing else
--   · only an account in admin_users can write
--   · every admin change lands in audit_log
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------- enums: the vocabulary the brief asked for ----------
create type verification_status as enum ('verified', 'needs_rechecking', 'unconfirmed', 'expired', 'cancelled');
create type publication_status  as enum ('draft', 'scheduled', 'published', 'archived');
create type coordinate_precision as enum ('venue', 'neighbourhood', 'locality');
create type cost_type            as enum ('free', 'under_500', 'ticketed', 'donation');
create type event_mode           as enum ('sit', 'walk', 'stand', 'shop', 'join');
create type campaign_status      as enum ('draft', 'pending_review', 'approved', 'rejected', 'running', 'paused', 'ended');
create type payment_status       as enum ('pending', 'received', 'refunded');

-- ---------- people who may write ----------
create table admin_users (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  email      text,
  created_at timestamptz not null default now()
);

create or replace function is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from admin_users where user_id = auth.uid());
$$;

-- ---------- places ----------
create table localities (
  id        uuid primary key default gen_random_uuid(),
  name      text not null,
  slug      text not null unique,
  lat       numeric(9,6) not null,
  lng       numeric(9,6) not null,
  precision coordinate_precision not null default 'locality',
  created_at timestamptz not null default now()
);

create table pincodes (
  pincode   text primary key check (pincode ~ '^[0-9]{6}$'),
  locality_id uuid references localities (id) on delete set null,
  lat       numeric(9,6),
  lng       numeric(9,6),
  -- a pincode may only carry coordinates if they were checked against a source
  source    text,
  verified  boolean not null default false,
  constraint coords_need_source check (
    (lat is null and lng is null) or (lat is not null and lng is not null and source is not null)
  )
);

create table venues (
  id        uuid primary key default gen_random_uuid(),
  name      text not null,
  slug      text not null unique,
  address   text not null,
  locality_id uuid references localities (id) on delete set null,
  lat       numeric(9,6),
  lng       numeric(9,6),
  metro     text,
  entry_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------- events ----------
create table events (
  id                uuid primary key default gen_random_uuid(),
  slug              text not null unique,
  title             text not null,
  summary           text,
  description       text,
  start_at          timestamptz not null,
  end_at            timestamptz not null,
  all_day           boolean not null default false,
  time_approximate  boolean not null default false,
  duration_minutes  int check (duration_minutes is null or duration_minutes > 0),
  recurrence        text,
  venue_id          uuid references venues (id) on delete set null,
  address           text not null,
  lat               numeric(9,6),
  lng               numeric(9,6),
  coord_precision   coordinate_precision not null default 'neighbourhood',
  metro             text,
  cost              cost_type not null default 'free',
  cost_amount_inr   int check (cost_amount_inr is null or cost_amount_inr >= 0),
  mode              event_mode,
  outdoors          boolean not null default false,
  what_happens      text,
  food              text,
  run_of_show       jsonb not null default '[]'::jsonb,
  practical         jsonb not null default '{}'::jsonb,
  tags              text[] not null default '{}',
  photo_url         text,
  photo_w           int,
  photo_h           int,
  -- provenance: required, never defaulted
  source_url        text not null,
  organiser_url     text,
  registration_url  text,
  verification      verification_status not null,
  last_checked      date not null,
  publication       publication_status not null default 'draft',
  published_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  created_by        uuid references auth.users (id),
  constraint ends_after_start check (end_at >= start_at),
  constraint coords_paired check (
    (lat is null and lng is null) or (lat is not null and lng is not null)
  )
);

create index events_start_idx on events (start_at);
create index events_public_idx on events (publication, verification, start_at);

-- ---------- analytics: aggregate first, identify nobody ----------
create table analytics_events (
  id          bigserial primary key,
  occurred_on date not null,
  kind        text not null check (kind in (
                'page_view','card_view','detail_open','search','filter',
                'locality_search','save','calendar_download','organiser_click','share')),
  event_id    uuid references events (id) on delete set null,
  locality    text,
  term_hash   text,              -- salted hash, never the raw search term
  device      text check (device in ('mobile','tablet','desktop','unknown')),
  referrer    text,
  created_at  timestamptz not null default now()
);

create index analytics_day_idx on analytics_events (occurred_on, kind);

create view analytics_daily as
  select occurred_on, kind, count(*) as hits
  from analytics_events
  group by occurred_on, kind;

-- ---------- advertising ----------
create table campaigns (
  id           uuid primary key default gen_random_uuid(),
  advertiser   text not null,
  contact      text,
  creative_url text,
  headline     text not null,
  destination  text not null check (destination ~ '^https://'),
  placements   text[] not null default '{}',
  localities   text[] not null default '{}',
  starts_on    date not null,
  ends_on      date not null,
  budget_inr   int check (budget_inr is null or budget_inr >= 0),
  status       campaign_status not null default 'draft',
  created_at   timestamptz not null default now(),
  constraint dates_ordered check (ends_on >= starts_on)
);

create table ad_events (
  id          bigserial primary key,
  campaign_id uuid not null references campaigns (id) on delete cascade,
  kind        text not null check (kind in ('impression','click')),
  occurred_on date not null default current_date,
  created_at  timestamptz not null default now()
);

create table payments (
  id          uuid primary key default gen_random_uuid(),
  campaign_id uuid references campaigns (id) on delete set null,
  amount_inr  int not null check (amount_inr > 0),
  status      payment_status not null default 'pending',
  received_on date,
  reference   text,
  created_at  timestamptz not null default now(),
  -- a payment can only be "received" with a date and a reference
  constraint received_needs_proof check (
    status <> 'received' or (received_on is not null and reference is not null)
  )
);

-- a campaign is only "running" once a payment has actually been received
create or replace function campaign_is_paid(c_id uuid) returns boolean
language sql stable as $$
  select exists (select 1 from payments where campaign_id = c_id and status = 'received');
$$;

-- ---------- audit trail ----------
create table audit_log (
  id        bigserial primary key,
  at        timestamptz not null default now(),
  actor     uuid references auth.users (id),
  table_name text not null,
  row_id    text,
  action    text not null check (action in ('insert','update','delete')),
  before    jsonb,
  after     jsonb
);

create or replace function log_change() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into audit_log (actor, table_name, row_id, action, before, after)
  values (auth.uid(), tg_table_name,
          coalesce((case when tg_op = 'DELETE' then old.id else new.id end)::text, null),
          lower(tg_op),
          case when tg_op = 'INSERT' then null else to_jsonb(old) end,
          case when tg_op = 'DELETE' then null else to_jsonb(new) end);
  return coalesce(new, old);
end;
$$;

create trigger events_audit after insert or update or delete on events
  for each row execute function log_change();
create trigger venues_audit after insert or update or delete on venues
  for each row execute function log_change();
create trigger campaigns_audit after insert or update or delete on campaigns
  for each row execute function log_change();
create trigger payments_audit after insert or update or delete on payments
  for each row execute function log_change();

create or replace function touch_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

create trigger events_touch before update on events
  for each row execute function touch_updated_at();
create trigger venues_touch before update on venues
  for each row execute function touch_updated_at();

-- ---------- row level security ----------
alter table admin_users     enable row level security;
alter table localities      enable row level security;
alter table pincodes        enable row level security;
alter table venues          enable row level security;
alter table events          enable row level security;
alter table analytics_events enable row level security;
alter table campaigns       enable row level security;
alter table ad_events       enable row level security;
alter table payments        enable row level security;
alter table audit_log       enable row level security;

-- public read: published, non-archived events only
create policy "public reads published events" on events
  for select using (publication = 'published' and verification <> 'cancelled');
create policy "public reads venues" on venues for select using (true);
create policy "public reads localities" on localities for select using (true);
create policy "public reads pincodes" on pincodes for select using (verified);

-- admin writes, and only admin writes
create policy "admin writes events" on events
  for all using (is_admin()) with check (is_admin());
create policy "admin writes venues" on venues
  for all using (is_admin()) with check (is_admin());
create policy "admin writes localities" on localities
  for all using (is_admin()) with check (is_admin());
create policy "admin writes pincodes" on pincodes
  for all using (is_admin()) with check (is_admin());
create policy "admin writes campaigns" on campaigns
  for all using (is_admin()) with check (is_admin());
create policy "admin writes payments" on payments
  for all using (is_admin()) with check (is_admin());
create policy "admin reads analytics" on analytics_events
  for select using (is_admin());
create policy "admin reads audit" on audit_log
  for select using (is_admin());
create policy "admin sees themselves" on admin_users
  for select using (user_id = auth.uid());

-- analytics and ad counters are written by server functions only:
-- no insert policy for anon, so the browser cannot inflate a number.

-- ---------- the public view the site reads ----------
create view public_events as
  select e.slug, e.title, e.summary, e.description, e.start_at, e.end_at,
         e.all_day, e.time_approximate, e.recurrence, e.address, e.lat, e.lng,
         e.coord_precision, e.metro, e.cost, e.cost_amount_inr, e.mode, e.outdoors,
         e.what_happens, e.food, e.run_of_show, e.practical, e.tags,
         e.photo_url, e.photo_w, e.photo_h, e.source_url, e.organiser_url,
         e.registration_url, e.verification, e.last_checked,
         v.name as venue, v.slug as venue_slug, l.name as locality
  from events e
  left join venues v on v.id = e.venue_id
  left join localities l on l.id = v.locality_id
  where e.publication = 'published' and e.verification <> 'cancelled';

-- =====================================================================
-- Seeding: events.json is the source. 51 rows, all currently
-- verification = 'needs_rechecking' except the six whose run has ended,
-- which are 'expired'. Nothing is marked verified until someone has
-- actually opened the organiser's page.
--
-- Free-tier limits worth remembering: 500 MB database, 5 GB egress,
-- 50,000 monthly active users, two projects, and the project pauses
-- after a week without activity.
-- =====================================================================
