"use client";

import * as React from "react";
import { OTPInput, OTPInputContext, type SlotProps } from "input-otp";
import { MinusIcon } from "lucide-react";

import { cn } from "./utils";

const SPACED_OTP_WIDTH = {
  4: "w-[11.5rem]",
  6: "w-[17.5rem]",
} as const;

function InputOTP({
  className,
  containerClassName,
  ...props
}: React.ComponentProps<typeof OTPInput> & {
  containerClassName?: string;
}) {
  return (
    <OTPInput
      data-slot="input-otp"
      containerClassName={cn(
        "flex items-center gap-2 has-disabled:opacity-50",
        containerClassName,
      )}
      className={cn("disabled:cursor-not-allowed", className)}
      {...props}
    />
  );
}

function InputOTPGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="input-otp-group"
      className={cn("flex items-center gap-1", className)}
      {...props}
    />
  );
}

function InputOTPSlot({
  index,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  index: number;
}) {
  const inputOTPContext = React.useContext(OTPInputContext);
  const { char, hasFakeCaret, isActive } = inputOTPContext?.slots[index] ?? {};

  return (
    <div
      data-slot="input-otp-slot"
      data-active={isActive}
      className={cn(
        "data-[active=true]:border-ring data-[active=true]:ring-ring/50 data-[active=true]:aria-invalid:ring-destructive/20 dark:data-[active=true]:aria-invalid:ring-destructive/40 aria-invalid:border-destructive data-[active=true]:aria-invalid:border-destructive dark:bg-input/30 border-input relative flex h-9 w-9 items-center justify-center border-y border-r text-sm bg-input-background transition-all outline-none first:rounded-l-md first:border-l last:rounded-r-md data-[active=true]:z-10 data-[active=true]:ring-[3px]",
        className,
      )}
      {...props}
    >
      {char}
      {hasFakeCaret && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="animate-caret-blink bg-foreground h-4 w-px duration-1000" />
        </div>
      )}
    </div>
  );
}

function InputOTPSeparator({ ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="input-otp-separator" role="separator" {...props}>
      <MinusIcon />
    </div>
  );
}

function SpacedOtpSlot({
  tone = "surface",
  ...props
}: SlotProps & { tone?: "login" | "surface" }) {
  const isLogin = tone === "login";
  const slotStyle: React.CSSProperties = {
    boxSizing: "border-box",
    width: "2.5rem",
    height: "2.5rem",
    borderRadius: "0.5rem",
    borderWidth: "1.5px",
    borderStyle: "solid",
    flexShrink: 0,
    ...(isLogin
      ? {
          borderColor: props.isActive ? "#2AABEE" : "rgba(0,0,0,0.1)",
          background: "#ffffff",
          color: "#0e0e0e",
          boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
        }
      : {
          borderColor: props.isActive ? "var(--sp-blue)" : "var(--sp-border)",
          background: "var(--sp-bg)",
          color: "var(--sp-text-primary)",
        }),
  };

  return (
    <div
      data-spaced-otp-slot=""
      className={cn(
        "relative flex items-center justify-center text-[15px] font-medium tabular-nums transition-shadow",
        props.isActive && !isLogin && "z-10 ring-[3px] ring-[var(--sp-blue)]/20",
        props.isActive && isLogin && "z-10 ring-[3px] ring-[#2AABEE]/20",
      )}
      style={slotStyle}
    >
      {props.char !== null ? props.char : null}
      {props.hasFakeCaret ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="h-4 w-px animate-caret-blink bg-[var(--sp-text-primary)] duration-1000" />
        </div>
      ) : null}
    </div>
  );
}

type SpacedOtpInputProps = {
  maxLength: 4 | 6;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  "aria-label": string;
  className?: string;
  tone?: "login" | "surface";
};

function SpacedOtpInput({
  maxLength,
  value,
  onChange,
  disabled,
  className,
  tone = "surface",
  "aria-label": ariaLabel,
}: SpacedOtpInputProps) {
  const widthClass = SPACED_OTP_WIDTH[maxLength];

  return (
    <InputOTP
      maxLength={maxLength}
      value={value}
      onChange={onChange}
      disabled={disabled}
      inputMode="numeric"
      autoComplete="one-time-code"
      aria-label={ariaLabel}
      containerClassName={cn("w-auto shrink-0", widthClass, className)}
      render={({ slots }) => (
        <div className={cn("flex gap-2", widthClass)}>
          {slots.map((slot, index) => (
            <SpacedOtpSlot key={index} tone={tone} {...slot} />
          ))}
        </div>
      )}
    />
  );
}

export { InputOTP, InputOTPGroup, InputOTPSlot, InputOTPSeparator, SpacedOtpInput };
