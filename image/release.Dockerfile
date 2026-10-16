# The release image (ADR-0029): the image the pipeline built once and its lanes tested, plus one final layer holding
# the tested.json that CI generated from the lanes that passed. The release workflow binds the named build context
# `tested` to that multi-arch index by digest (oci-layout://<layout>@sha256:<index digest>), and the build context
# holds only tested.json. No other instruction, so every other layer and the runtime configuration stay the tested ones.
FROM tested
COPY --chmod=0644 tested.json /usr/local/lib/python3.13/site-packages/ingat/tested.json
