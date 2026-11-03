// `/access/people?tab=&member=&group=`: the org directory. Members with their effective access per instance, groups
// (manual or synced by SCIM), invitations and temporary access requests; the selected member or group opens in an
// aside, and both deep-link (the audit log and notifications link here).
import { apiUrl, directoryScimStatusOptions } from "@agnostic/api";
import { PermissionGate, formatRelative, useCan, useMe, withQueryFn } from "@agnostic/core";
import {
  Button,
  PageIntro,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  buttonVariants,
  cn,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Download, UserPlus } from "lucide-react";
import { useState } from "react";

import { GroupAside } from "./group-aside";
import { GroupsTab } from "./groups-tab";
import { InvitationsTab, InviteDialog, useInvitations } from "./invitations-tab";
import { MemberAside } from "./member-aside";
import { MembersTab } from "./members-tab";
import { usePeopleSearch, useDirectory, type PeopleTab } from "./people-api";
import { RequestsTab, useRequests } from "./requests-tab";

/** "● Okta SCIM · synced 4 min ago" when an IdP provisions people; nothing otherwise. */
function ScimPill() {
  const scim = useQuery({ ...withQueryFn(directoryScimStatusOptions()), retry: false });
  const token =
    scim.data?.tokens.find((item) => item.state === "active") ??
    scim.data?.tokens.find((item) => item.state === "rotating");
  if (!scim.data || !token) return null;
  const synced = scim.data.last_request_at
    ? `synced ${formatRelative(scim.data.last_request_at)}`
    : "waiting for the first sync";
  return (
    <span
      role="status"
      title={scim.data.last_error ?? undefined}
      className="inline-flex h-6 items-center gap-1.5 rounded-full border border-border-strong px-2.5 text-[12px] text-fg-secondary"
    >
      <span
        aria-hidden
        className={cn("size-1.5 rounded-full", scim.data.healthy ? "bg-accent" : "bg-warning")}
      />
      {token.label} · {synced}
      {!scim.data.healthy && " · last request failed"}
    </span>
  );
}

export function PeoplePage() {
  const [state, go] = usePeopleSearch();
  const directory = useDirectory();
  const me = useMe();
  const canBind = useCan("org:roles:write").allowed === true;
  const [inviting, setInviting] = useState(false);
  const invitations = useInvitations();
  const pendingRequests = useRequests(false);

  const pending = pendingRequests.data ?? [];
  const showRequests =
    canBind ||
    state.tab === "requests" ||
    pending.some((request) => request.can_decide === true || request.requester_id === me.data?.id);
  const member = state.member
    ? directory.allMembers.find((item) => item.user_id === state.member)
    : undefined;
  const count = (value: number | undefined) => (value === undefined ? {} : { count: value });

  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro
        title="People & groups"
        actions={
          <>
            <ScimPill />
            <a
              href={apiUrl("/api/v1/members/export.csv")}
              download
              className={buttonVariants({ variant: "outline", size: "34" })}
            >
              <Download aria-hidden />
              Export CSV
            </a>
            <PermissionGate scope="org:members:write">
              <Button
                variant="primary"
                onClick={() => {
                  setInviting(true);
                }}
              >
                <UserPlus aria-hidden />
                Invite people
              </Button>
            </PermissionGate>
          </>
        }
      >
        An org role controls the control plane. Access roles, given directly or through a group, control what
        someone can do on each AgentOS instance.
      </PageIntro>
      <Tabs
        value={state.tab}
        onValueChange={(tab) => {
          go({ tab: tab as PeopleTab });
        }}
      >
        <TabsList aria-label="People">
          <TabsTrigger value="members" {...count(directory.members.data?.length)}>
            Members
          </TabsTrigger>
          <TabsTrigger value="groups" {...count(directory.groupsQuery.data?.length)}>
            Groups
          </TabsTrigger>
          <TabsTrigger
            value="invitations"
            {...count(invitations.data?.filter((invitation) => invitation.status === "pending").length)}
          >
            Invitations
          </TabsTrigger>
          {showRequests && (
            <TabsTrigger
              value="requests"
              countTone={pending.some((request) => request.can_decide) ? "warning" : "muted"}
              {...count(pendingRequests.data?.length)}
            >
              Requests
            </TabsTrigger>
          )}
        </TabsList>
        <TabsContent value="members" className="pt-2">
          <MembersTab directory={directory} state={state} go={go} />
        </TabsContent>
        <TabsContent value="groups" className="pt-2">
          <GroupsTab directory={directory} state={state} go={go} />
        </TabsContent>
        <TabsContent value="invitations" className="pt-2">
          <InvitationsTab directory={directory} />
        </TabsContent>
        {showRequests && (
          <TabsContent value="requests" className="pt-2">
            <RequestsTab directory={directory} state={state} go={go} />
          </TabsContent>
        )}
      </Tabs>
      {member && <MemberAside key={member.user_id} member={member} directory={directory} go={go} />}
      {state.group && !member && (
        <GroupAside key={state.group} groupId={state.group} directory={directory} go={go} />
      )}
      <InviteDialog open={inviting} onOpenChange={setInviting} directory={directory} />
    </div>
  );
}
