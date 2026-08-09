import installerBase64 from "./install.generated.js";
import { handleRequest } from "./handler.js";

const installer = Uint8Array.from(atob(installerBase64), (character) =>
  character.charCodeAt(0),
);

export default {
  fetch(request) {
    return handleRequest(request, installer);
  },
};
