// Notification fixtures: the bell's inbox, personal preferences, the org's Slack channel and defaults, the
// approval expiry policy; plus MSW handlers for them.
import type {
  ChannelOut,
  DefaultsBody,
  EventTypeOut,
  NotificationOut,
  PolicyOut,
  PreferencesOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { PROD } from "./sample-org";

const T = "2026-11-03T14:52:00Z";

export const sampleEventTypes: EventTypeOut[] = [
  {
    name: "approval.created",
    label: "Approval requested",
    description: "A run paused for an approval routed to you.",
    defaults: ["in_app"],
  },
  {
    name: "schedule.failed",
    label: "Schedule failed",
    description: "A scheduled run failed.",
    defaults: ["in_app"],
  },
];

export const sampleNotifications: NotificationOut[] = [
  {
    id: "ntf_1",
    kind: "approval.created",
    title: "refund_customer needs approval",
    body: "agent billing-agent · amount=49.0",
    link: "/i/prod-agentos/approvals?approval=apv_7Kq2",
    instance_id: PROD,
    data: { approval_id: "apv_7Kq2" },
    created_at: T,
    read_at: null,
  },
];

export const samplePreferences: PreferencesOut = {
  events: sampleEventTypes.map((event) => ({ event, channels: event.defaults, custom: false })),
  quiet_hours: null,
  slack_available: true,
};

export const sampleSlackChannel: ChannelOut = {
  id: "nch_billing",
  kind: "slack",
  name: "Slack · billing-ops",
  config: { mode: "bot", token: "…oken", channel: "C0BILLING", direct_messages: true },
  events: [],
  instance_ids: [],
  enabled: true,
  sends_direct_messages: true,
  created_at: T,
  updated_at: T,
  recent: [],
};

export const samplePolicy: PolicyOut = {
  instance_id: PROD,
  enforce_expiry: false,
  ttl_hours: null,
  updated_by: null,
  updated_at: null,
};

export function notificationsHandlers() {
  let preferences = structuredClone(samplePreferences);
  const defaults: DefaultsBody = {
    events: { "approval.created": ["in_app"], "schedule.failed": ["in_app"] },
  };
  return [
    http.get(`${API}/notifications/unread-count`, () =>
      HttpResponse.json({ unread: sampleNotifications.length }),
    ),
    http.get(`${API}/notifications`, () =>
      HttpResponse.json({ data: sampleNotifications, next_cursor: null, total_estimate: null }),
    ),
    http.post(`${API}/notifications/read`, () => HttpResponse.json({ changed: 1, unread: 0 })),
    http.get(`${API}/notifications/event-types`, () => HttpResponse.json(sampleEventTypes)),
    http.get(`${API}/notifications/defaults`, () => HttpResponse.json(defaults)),
    http.put(`${API}/notifications/defaults`, async ({ request }) => {
      const body = (await request.json()) as DefaultsBody;
      Object.assign(defaults.events, body.events);
      return HttpResponse.json(defaults);
    }),
    http.get(`${API}/notifications/channels`, () => HttpResponse.json([sampleSlackChannel])),
    http.get(`${API}/me/notification-preferences`, () => HttpResponse.json(preferences)),
    http.put(`${API}/me/notification-preferences`, async ({ request }) => {
      const body = (await request.json()) as {
        events?: Record<string, PreferencesOut["events"][number]["channels"]>;
      };
      preferences = {
        ...preferences,
        events: preferences.events.map((item) => {
          const next = body.events?.[item.event.name];
          return next ? { ...item, channels: next, custom: true } : item;
        }),
      };
      return HttpResponse.json(preferences);
    }),
    http.get(`${API}/instances/:instance/approvals/policy`, () => HttpResponse.json(samplePolicy)),
  ];
}
