"""Plugin-owned default-template and backend-resolution regressions."""

from __future__ import annotations

from avac_qgis.core.configuration import load_complete_configuration
from avac_qgis.core.runtime_assets import bundled_backend_directory, default_template_path


def main() -> None:
    template = default_template_path()
    configuration = load_complete_configuration(template)
    assert configuration["computation"]["cell_size"] == 2
    assert configuration["release"]["period_return"] == 100
    # A source checkout deliberately resolves its development fixture; an
    # installed build will supply resources/backend/AVAC at the same API path.
    assert bundled_backend_directory().name == "AVAC"
    print("plugin-owned default template and automatic backend resolution: PASS")


if __name__ == "__main__":
    main()
