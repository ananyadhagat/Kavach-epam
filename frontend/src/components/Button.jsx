export default function Button({
  children,
  className = "",
  variant = "primary",
  ...props
}) {
  return (
    <button
      className={`button button--${variant} ${className}`.trim()}
      {...props}
    >
      {children}
    </button>
  );
}
