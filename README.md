# Experimental Suite Instructions

To run the full experimental suite, clone the repository and use the following commands, replacing the values in angle brackets with the appropriate paths and settings:

```sh
cd <repository-root>
python3.14 -m venv .venv

.venv/bin/pip install -r requirements.txt

sh run.sh \
    --workers <number-of-workers> \
    --output <output-directory>
```

The original `requirements.txt` preserves the dependency hashes used for this work and targets Python 3.14 on Apple Silicon macOS 14 or later. For experimenting on other platforms, use `requirements2.txt` instead. The dependency versions remain the same.

Using the original environment and unchanged settings, the results should be the same as the ones reported in this work as long as the supplied seed does not change. Changing the seed will also change the random day selection, potentially changing the specific set identities. Nonetheless, the broader findings should remain largely similar, as observed across missions and years.

The validation suite is not included in the repository, so the total runtime should be noticeably shorter.
