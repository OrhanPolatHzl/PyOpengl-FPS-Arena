import math
import unittest

import numpy as np

from main import (
    PLAYER_RADIUS,
    Box,
    FPSPlayer,
    create_cube_vertices,
    make_arena,
    normalized,
    perspective,
)


class GeometryTests(unittest.TestCase):
    def test_cube_triangle_winding_and_normals(self):
        vertices = create_cube_vertices().reshape(-1, 6)
        self.assertEqual(vertices.shape, (36, 6))
        for tri in vertices.reshape(-1, 3, 6):
            p0, p1, p2 = tri[:, :3]
            geometric_normal = normalized(np.cross(p1 - p0, p2 - p0))
            declared_normal = tri[0, 3:]
            self.assertGreater(float(np.dot(geometric_normal, declared_normal)), 0.99)

    def test_perspective_valid(self):
        proj = perspective(72, 16 / 9, 0.07, 190.0)
        self.assertEqual(proj.shape, (4, 4))
        self.assertTrue(np.isfinite(proj).all())
        self.assertAlmostEqual(float(proj[3, 2]), -1)

    def test_model_matrix_transform(self):
        model = Box(2, 3, 4, 6, 8, 10, (1, 0, 0)).model_matrix()
        p = model @ np.array([0.5, 0.5, 0.5, 1.0], dtype=np.float32)
        np.testing.assert_allclose(p, [5, 7, 9, 1])


class PlayerCollisionTests(unittest.TestCase):
    def setUp(self):
        self.scene = make_arena()
        self.player = FPSPlayer()

    def test_spawn_is_free(self):
        self.assertFalse(self.player.collides(self.player.x, self.player.z, self.scene))

    def test_can_not_enter_crate(self):
        crate = next(box for box in self.scene if box.x == -17 and box.z == -3)
        self.assertTrue(self.player.collides(crate.x, crate.z, self.scene))

    def test_perimeter_wall_is_solid(self):
        self.assertTrue(self.player.collides(0.0, 30.9, self.scene))

    def test_substeps_stop_fast_player_at_cover(self):
        self.player.x, self.player.z = 0.0, 0.0
        self.player.speed = 200.0
        self.player.move(0.10, self.scene, True, False, False, False)
        # The blocker centered at z=-10 has half-depth .45.
        self.assertGreaterEqual(self.player.z, -10 + 0.45 + PLAYER_RADIUS - 0.002)

    def test_diagonal_input_is_normalized(self):
        a = FPSPlayer()
        b = FPSPlayer()
        a.move(0.016, [], True, False, False, False)
        b.move(0.016, [], True, False, False, True)
        dist_a = math.hypot(a.x, a.z - 18)
        dist_b = math.hypot(b.x, b.z - 18)
        self.assertAlmostEqual(dist_a, dist_b, delta=1e-5)


if __name__ == "__main__":
    unittest.main()
