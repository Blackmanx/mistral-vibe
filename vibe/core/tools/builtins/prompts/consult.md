Ask a cheap second-opinion model a focused question. It has no tools and cannot inspect the repository, so pass the relevant code, error, or plan excerpt in `context`.

Use for quick checks where a second perspective helps: reviewing a small patch, choosing between two approaches, explaining an error, or sanity-checking a plan. Do not use it for work you can verify directly, and do not delegate the actual task to it.

`image_paths` attaches images from the workspace, such as a screenshot or a diagram. Only pass paths when the configured consult model accepts images.
