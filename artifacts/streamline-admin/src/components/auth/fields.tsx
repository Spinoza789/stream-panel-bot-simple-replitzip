import { useId, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  error?: string;
  hint?: ReactNode;
  secret?: boolean;
  testid: string;
};

export function Field({ label, error, hint, secret, testid, className, type, ...rest }: FieldProps) {
  const id = useId();
  const [show, setShow] = useState(false);
  const descId = `${id}-desc`;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      <div className="relative">
        <Input
          id={id}
          type={secret ? (show ? "text" : "password") : type}
          aria-invalid={!!error}
          aria-describedby={error || hint ? descId : undefined}
          spellCheck={false}
          autoCapitalize="off"
          className={cn("h-10", secret && "pr-10", error && "border-[hsl(4_65%_50%)]", className)}
          data-testid={testid}
          {...rest}
        />
        {secret && (
          <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground" aria-label={show ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`} data-testid={`${testid}-toggle`}>
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        )}
      </div>
      {(error || hint) && (
        <p id={descId} className={cn("text-xs", error ? "text-[hsl(4_60%_36%)]" : "text-muted-foreground")} role={error ? "alert" : undefined}>{error || hint}</p>
      )}
    </div>
  );
}

export function FormAlert({ children, testid }: { children: ReactNode; testid: string }) {
  return <p role="alert" className="rounded-lg bg-[hsl(4_70%_97%)] px-3 py-2 text-sm text-[hsl(4_60%_30%)]" data-testid={testid}>{children}</p>;
}

export const USERNAME_RE = /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/;
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function usernameError(v: string) {
  if (v.length < 3 || v.length > 32) return "Use 3 to 32 characters.";
  if (!USERNAME_RE.test(v)) return "Letters, numbers, underscore, dot or dash. Can't start with a dot or dash.";
  return undefined;
}
export function emailError(v: string) {
  if (!v || v.length > 254 || !EMAIL_RE.test(v)) return "Enter a valid email address.";
  return undefined;
}
export function newPasswordError(v: string) {
  if (v.length < 12) return "At least 12 characters.";
  if (v.length > 128) return "At most 128 characters.";
  return undefined;
}
