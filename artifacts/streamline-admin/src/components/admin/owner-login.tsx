import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetPasswordAccount,
  getGetPasswordAccountQueryKey,
  useUpdatePasswordAccount,
  getGetCurrentAuthUserQueryKey,
  getGetAdminAccessQueryKey,
} from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Bar, ErrorState, Panel } from "./bits";
import { useAdminReady } from "./access";
import { Field, FormAlert, emailError, newPasswordError, usernameError } from "@/components/auth/fields";
import { errorMessage, errorStatus } from "@/lib/format";
import { useToast } from "@/hooks/use-toast";

export function OwnerLoginPanel() {
  const ready = useAdminReady();
  const qc = useQueryClient();
  const { toast } = useToast();
  const acc = useGetPasswordAccount({ query: { enabled: ready, queryKey: getGetPasswordAccountQueryKey() } });
  const upd = useUpdatePasswordAccount();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState(false);
  const inited = useRef(false);

  useEffect(() => {
    if (acc.data && !inited.current) {
      inited.current = true;
      setUsername(acc.data.username);
      setEmail(acc.data.email);
    }
  }, [acc.data]);

  const errs = {
    username: usernameError(username),
    email: emailError(email.trim()),
    current: !current ? "Enter your current password to save changes." : undefined,
    next: next ? newPasswordError(next) : undefined,
    confirm: next && confirm !== next ? "Passwords don't match." : undefined,
  };
  const valid = !Object.values(errs).some(Boolean);
  const show = (k: keyof typeof errs) => (touched ? errs[k] : undefined);
  const clearSecrets = () => { setCurrent(""); setNext(""); setConfirm(""); };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid || upd.isPending) return;
    upd.mutate(
      { data: { username, email: email.trim(), currentPassword: current, ...(next ? { newPassword: next } : {}) } },
      {
        onSuccess: (a) => {
          clearSecrets();
          setTouched(false);
          setUsername(a.username);
          setEmail(a.email);
          qc.setQueryData(getGetPasswordAccountQueryKey(), a);
          qc.invalidateQueries({ queryKey: getGetPasswordAccountQueryKey() });
          qc.invalidateQueries({ queryKey: getGetCurrentAuthUserQueryKey() });
          qc.invalidateQueries({ queryKey: getGetAdminAccessQueryKey() });
          toast({ title: "Owner login updated", description: "Other sessions were signed out. This browser stays signed in." });
        },
        onError: () => { clearSecrets(); setTouched(false); },
      },
    );
  };

  const st = upd.isError ? errorStatus(upd.error) : undefined;
  const fail = st === 401 || st === 403 ? "Current password isn't right." : st === 409 ? "That username or email is already in use." : st === 429 ? "Too many attempts. Wait a few minutes and try again." : upd.isError ? errorMessage(upd.error) : "";

  return (
    <Panel title="Owner login">
      <p className="mb-4 text-xs leading-relaxed text-muted-foreground">Your own local account for this desk. Changing it signs out every other session.</p>
      {acc.isError ? <ErrorState message={errorMessage(acc.error)} onRetry={() => acc.refetch()} /> : !acc.data ? (
        <div className="space-y-3"><Bar className="h-10" /><Bar className="h-10" /><Bar className="h-10" /></div>
      ) : (
        <form onSubmit={submit} noValidate className="space-y-4" data-testid="form-owner-login">
          <Field label="Username" testid="input-account-username" name="username" autoComplete="username" value={username} maxLength={32} onChange={(e) => setUsername(e.target.value)} error={show("username")} />
          <Field label="Email" testid="input-account-email" type="email" name="email" autoComplete="email" value={email} maxLength={254} onChange={(e) => setEmail(e.target.value)} error={show("email")} />
          <div className="border-t border-border pt-4 space-y-4">
            <Field label="New password" testid="input-account-new-password" name="new-password" secret autoComplete="new-password" value={next} maxLength={128} onChange={(e) => setNext(e.target.value)} error={show("next")} hint="Optional. Leave blank to keep the current one. 12 to 128 characters." />
            {next && <Field label="Confirm new password" testid="input-account-confirm-password" name="confirm-password" secret autoComplete="new-password" value={confirm} maxLength={128} onChange={(e) => setConfirm(e.target.value)} error={show("confirm")} />}
            <Field label="Current password" testid="input-account-current-password" name="current-password" secret autoComplete="current-password" value={current} maxLength={128} onChange={(e) => setCurrent(e.target.value)} error={show("current")} hint="Required to save any change." />
          </div>
          {fail && <FormAlert testid="text-account-error">{fail}</FormAlert>}
          <Button type="submit" className="w-full" disabled={upd.isPending} data-testid="button-save-account">
            {upd.isPending ? "Saving..." : "Save login"}
          </Button>
        </form>
      )}
    </Panel>
  );
}
