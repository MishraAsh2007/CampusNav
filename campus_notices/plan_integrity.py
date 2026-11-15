"""Fingerprints of the exact drawing editions used for authored geometry.

A successful scrape of a newer plan must not silently reuse the older trace.
"""

REVIEWED_HASHES = {
    "cc-2026-conference-program.pdf": (
        "7082e1cf28ce545e4fe13d91b7f5226039ead24e41f018364ba6af3405cd8941"
    ),
    "707-01.pdf": "5cdd568075bd850265c8afbba5f8deb7cd57aa61990657e169e3f328f30b05dd",
    "707-02.pdf": "ddba0a96dd0dd9cd99822f22cd5d7500c0ce1a5afc92d13d9afc7a8392e791ed",
    "707-03.04.pdf": "96f5ad04cd0526234a4310a1728ebab49bb7b25bc6e46404aa56ac2273f4d197",
    "707-05.pdf": "1bc82775eb7e854f4862a3c1388ca573e89e8fd60a4d1c75e77ef1f26dc62b7f",
    "707-06.pdf": "7751e287b15c5381f16946e47e9cf7003f0aadff54a6383c6c0eee4694d131d5",
    "first-floor.png": "3b54652611621f71d1c5b7e736c3a5849aab16891fd05977ba30b9c40419eddb",
    "second-floor.jpg": "590cebae81e74d42b947dca63ed798d3e53503d9290cc41862712f6bdd07ef76",
    "eight-floor.jpg": "320c07341f6127e435a07950d548f522bdc4882be8a5a952c5e27c1aa6c6a100",
    "ten-11-floor.jpg": "eeedcd3c4e23c787f5e19b336c8c78ea48f26871b34c356ffd0dbade78b6ec10",
}


def require_reviewed_source(name, digest):
    if REVIEWED_HASHES.get(name) != digest:
        raise ValueError(
            f"{name}: source edition differs from the authored trace; re-inspect before publication"
        )
