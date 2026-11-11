type Props = {
  title: string;
  hint?: string;
};

export function StorefrontStubPage({ title, hint }: Props) {
  return (
    <main
      className="bg-sp-bg text-sp-text-primary min-h-[60vh]"
      style={{ maxWidth: 720, margin: "0 auto", padding: "6rem 1.5rem 4rem", textAlign: "center" }}
    >
      <h1 className="text-[clamp(2rem,5vw,3rem)] font-semibold tracking-tight mb-4 m-0">
        {title}
      </h1>
      {hint ? (
        <p className="text-sp-text-secondary leading-relaxed text-[1.05rem] m-0">{hint}</p>
      ) : null}
    </main>
  );
}
