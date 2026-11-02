import assert from "node:assert/strict";
import test from "node:test";
import { makeApiError } from "../src/api/errors.js";

test("keeps the backend field path and validation message for worker feedback", async () => {
  const response = new Response(
    JSON.stringify({
      detail: [
        {
          loc: ["body", "latitude"],
          msg: "Input should be less than or equal to 90",
          type: "less_than_equal",
        },
      ],
    }),
    {
      status: 422,
      headers: { "content-type": "application/json" },
    },
  );

  const error = await makeApiError(response, null);

  assert.equal(error.status, 422);
  assert.match(error.message, /body\.latitude: Input should be less than or equal to 90/);
});
