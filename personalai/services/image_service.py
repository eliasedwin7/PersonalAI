"""Image generation via Stable Diffusion Forge (an AUTOMATIC1111-style
webui) - a prompt, or a prompt + an uploaded reference image, the same
shape as ChatGPT's image tool. See the approved plan
(you-are-a-senior-crystalline-sloth.md, Track B) for why Forge was
picked over ComfyUI for this specific feature: Forge's REST API takes a
flat JSON body and returns base64 PNGs directly, no node graph to build.

Dependency-free (stdlib urllib only), matching ollama_client.py's own
style. Credentials are read from FORGE_USERNAME/FORGE_PASSWORD
environment variables by build_forge_client() - never stored in
config.json, the same convention already established for
ANTHROPIC_API_KEY/OPENAI_API_KEY in core/config.py.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from personalai.core.config import Config
from personalai.core.errors import PersonalAIError, UserFacingError

PROBE_TIMEOUT_S = 5
GENERATE_TIMEOUT_S = 300  # image generation can genuinely take a couple of minutes on CPU/older GPUs


class ForgeUnavailable(PersonalAIError):
    """Forge specifically isn't reachable - its own subclass (like
    OllamaUnavailable) so callers can give backend-specific guidance
    ("is Forge running? is the URL right?") while generic code can
    catch PersonalAIError and handle it the same way regardless."""


class ForgeClient:
    def __init__(self, base_url: str, username: str | None = None,
                password: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _auth_header(self) -> dict[str, str]:
        if not self.username:
            return {}
        credentials = f"{self.username}:{self.password or ''}"
        token = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _request(self, method: str, path: str, body: dict | None = None,
                timeout: float = GENERATE_TIMEOUT_S) -> dict:
        headers = {"Content-Type": "application/json", **self._auth_header()}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            if exc.code in (401, 403):
                raise UserFacingError(
                    f"Forge rejected the request (HTTP {exc.code}) - check "
                    "FORGE_USERNAME/FORGE_PASSWORD if it's gated with --gradio-auth."
                ) from exc
            raise UserFacingError(f"Forge rejected the request: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ForgeUnavailable(
                f"Cannot reach Forge at {self.base_url}: {exc}\n"
                "Is it running (webui-user.bat with --api), and is forge_url correct?"
            ) from exc

    def health(self) -> bool:
        try:
            headers = self._auth_header()
            req = urllib.request.Request(self.base_url + "/sdapi/v1/options", headers=headers)
            with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def list_checkpoints(self) -> list[str]:
        try:
            models = self._request("GET", "/sdapi/v1/sd-models", timeout=PROBE_TIMEOUT_S)
        except PersonalAIError:
            return []
        return [m.get("title", m.get("model_name", "")) for m in models]

    def set_checkpoint(self, name: str) -> None:
        self._request("POST", "/sdapi/v1/options",
                      {"sd_model_checkpoint": name}, timeout=PROBE_TIMEOUT_S)

    def txt2img(
        self, prompt: str, negative_prompt: str = "", steps: int = 20, cfg: float = 7.0,
        width: int = 512, height: int = 512, seed: int = -1,
    ) -> bytes:
        body = {
            "prompt": prompt, "negative_prompt": negative_prompt, "steps": steps,
            "cfg_scale": cfg, "width": width, "height": height, "seed": seed,
        }
        result = self._request("POST", "/sdapi/v1/txt2img", body)
        return self._first_image(result)

    def img2img(
        self, prompt: str, reference_image: bytes, negative_prompt: str = "",
        denoising_strength: float = 0.75, steps: int = 20, cfg: float = 7.0,
        width: int = 512, height: int = 512, seed: int = -1,
    ) -> bytes:
        init_image_b64 = base64.b64encode(reference_image).decode()
        body = {
            "prompt": prompt, "negative_prompt": negative_prompt, "steps": steps,
            "cfg_scale": cfg, "width": width, "height": height, "seed": seed,
            "denoising_strength": denoising_strength, "init_images": [init_image_b64],
        }
        result = self._request("POST", "/sdapi/v1/img2img", body)
        return self._first_image(result)

    @staticmethod
    def _first_image(result: dict) -> bytes:
        images = result.get("images") or []
        if not images:
            raise UserFacingError("Forge returned no image - check the prompt/parameters.")
        return base64.b64decode(images[0])


def build_forge_client(config: Config) -> ForgeClient:
    return ForgeClient(
        base_url=config.forge_url,
        username=os.environ.get("FORGE_USERNAME"),
        password=os.environ.get("FORGE_PASSWORD"),
    )
