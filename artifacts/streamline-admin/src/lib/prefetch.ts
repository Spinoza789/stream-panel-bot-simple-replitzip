import type { QueryClient } from "@tanstack/react-query";
import {
  getListAdminOrdersQueryOptions, getListAdminSubscriptionGroupsQueryOptions, getListAdminResellersQueryOptions,
  getListAdminTicketsQueryOptions, getListAdminActivityLogQueryOptions, getGetAdminReportsQueryOptions,
  getGetAdminRateCardQueryOptions, getGetAdminFaqQueryOptions, getGetAdminStatusQueryOptions, getGetAdminOverviewQueryOptions,
} from "@workspace/api-client-react";

// Data fetched ahead of a click is reused if it is younger than this; the page still refreshes
// itself in the background when opened, so nothing shown is ever older than a normal visit.
const FRESH_MS = 25_000;

type Options = { queryKey: readonly unknown[] };
/** What each screen asks for when it first opens, with the same parameters the screen itself uses. */
const SCREENS: Record<string, () => Options[]> = {
  "/dashboard": () => [getGetAdminOverviewQueryOptions()],
  "/orders": () => [getListAdminOrdersQueryOptions({ page: 1 })],
  "/trials": () => [getListAdminSubscriptionGroupsQueryOptions({ kind: "trial" })],
  "/subscriptions": () => [getListAdminSubscriptionGroupsQueryOptions({ kind: "paid" })],
  "/resellers": () => [getListAdminResellersQueryOptions({ page: 1 })],
  "/tickets": () => [getListAdminTicketsQueryOptions({ status: "open", page: 1 })],
  "/reports": () => [getGetAdminReportsQueryOptions({ months: 12 })],
  "/logs": () => [getListAdminActivityLogQueryOptions({ page: 1 })],
  "/settings": () => [getGetAdminRateCardQueryOptions(), getGetAdminFaqQueryOptions(), getGetAdminStatusQueryOptions()],
};

/** The screens most often opened next, in the order they are fetched after the first page has loaded. */
const LIKELY_NEXT = ["/orders", "/subscriptions", "/trials", "/resellers", "/tickets"];

/** Fetch one screen's data ahead of time. Failures are ignored: the screen will ask again when opened. */
export function prefetchScreen(qc: QueryClient, href: string): Promise<unknown> {
  const queries = SCREENS[href]?.() ?? [];
  return Promise.all(queries.map((q) => qc.prefetchQuery({ ...(q as Parameters<QueryClient["prefetchQuery"]>[0]), staleTime: FRESH_MS })));
}

// The sidebar is rebuilt on every navigation, so this is throttled here: unused copies are dropped
// from memory after five minutes, and warming again just before that keeps them available.
const REWARM_MS = 4 * 60_000;
let warmedAt = 0;

/** One at a time, so warming the cache never competes with the page the owner is actually looking at. */
export async function prefetchLikelyScreens(qc: QueryClient, current: string, cancelled: () => boolean): Promise<void> {
  if (Date.now() - warmedAt < REWARM_MS) return;
  warmedAt = Date.now();
  for (const href of LIKELY_NEXT) {
    if (cancelled()) return;
    if (href !== current) await prefetchScreen(qc, href);
  }
}
