# ILR (isometric log-ratio) transforms for composition vectors.
# Needed because the GP kernel assumes Euclidean space, but mutation weights
# live on a simplex. ILR maps the simplex isometrically into R^(k-1) so
# Euclidean distances there equal Aitchison distances on the simplex.
# See Egozcue et al. (2003), Mathematical Geology 35(3).

import numpy as np


_EPS = 1e-10


def _helmert_row(i: int, k: int) -> np.ndarray:
    row = np.zeros(k)
    row[:i] = np.sqrt(1.0 / (i * (i + 1)))
    row[i]  = -np.sqrt(i / (i + 1))
    return row


def _helmert_matrix(k: int) -> np.ndarray:
    return np.array([_helmert_row(i, k) for i in range(1, k)])


def ilr_forward(w: np.ndarray) -> np.ndarray:
    """Simplex -> R^(k-1). Clips and renormalises first to handle boundary noise."""
    w = np.asarray(w, dtype=float)
    w = np.clip(w, _EPS, None)
    w = w / w.sum()
    Psi = _helmert_matrix(len(w))
    return Psi @ np.log(w)


def ilr_inverse(z: np.ndarray) -> np.ndarray:
    """R^(k-1) -> simplex."""
    z = np.asarray(z, dtype=float)
    k = len(z) + 1
    Psi = _helmert_matrix(k)
    clr = Psi.T @ z
    clr -= clr.max()
    w = np.exp(clr)
    return w / w.sum()


def sample_simplex(k: int, rng: np.random.Generator) -> np.ndarray:
    """Uniform sample from the (k-1)-simplex via exponential normalisation."""
    x = rng.exponential(1.0, size=k)
    return x / x.sum()


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    for _ in range(10_000):
        k = 5
        w = sample_simplex(k, rng)
        z = ilr_forward(w)
        w2 = ilr_inverse(z)
        assert np.allclose(w, w2, atol=1e-10), f"round-trip failed: {w} vs {w2}"
    print("ILR round-trip test passed (10 000 samples, k=5).")

    w1 = sample_simplex(5, rng)
    w2 = sample_simplex(5, rng)
    aitchison = np.sqrt(np.sum((np.log(w1) - np.log(w2)
                                - (np.log(w1) - np.log(w2)).mean()) ** 2))
    euclidean = np.linalg.norm(ilr_forward(w1) - ilr_forward(w2))
    assert np.isclose(aitchison, euclidean, rtol=1e-6), \
        f"isometry check failed: {aitchison:.6f} vs {euclidean:.6f}"
    print("ILR isometry check passed.")
