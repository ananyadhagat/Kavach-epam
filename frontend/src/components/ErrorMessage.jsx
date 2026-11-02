export default function ErrorMessage({ children, title = "Something went wrong" }) {
  return (
    <section className="message-panel message-panel--error" role="alert">
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}
