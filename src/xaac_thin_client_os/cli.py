"""Command-line interface for the XAAC Thin Client OS constructor."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xaac_thin_client_os.apt import (
    AptConfigurationError,
    AptConfigurator,
    create_apt_configuration_plan,
)
from xaac_thin_client_os.bootstrap import BootstrapError, BootstrapRunner, create_bootstrap_plan
from xaac_thin_client_os.build_dependencies import BuildDependencyError, require_build_dependencies
from xaac_thin_client_os.bootable_image import (
    BootableImageBuilder, BootableImageError, create_bootable_image_plan,
)
from xaac_thin_client_os.configuration import ConfigurationError, load_project_configuration
from xaac_thin_client_os.hooks import HookError, HookRunner
from xaac_thin_client_os.emmc_support import (
    EmmcConfigurator, EmmcDetector, EmmcSupportError, compare_emmc,
    create_emmc_configuration_plan, load_emmc_profile, write_emmc_report,
)
from xaac_thin_client_os.intel_graphics import (
    IntelGraphicsConfigurator, IntelGraphicsDetector, IntelGraphicsError, compare_graphics,
    create_graphics_configuration_plan, load_graphics_profile, write_graphics_report,
)
from xaac_thin_client_os.graphical_stack import (
    GraphicalStackConfigurator, GraphicalStackError, create_graphical_stack_plan,
)
from xaac_thin_client_os.compositor import (
    CompositorConfigurator, CompositorError, create_compositor_plan,
)
from xaac_thin_client_os.session_manager import (
    SessionManagerConfigurator, SessionManagerError, create_session_manager_plan,
)
from xaac_thin_client_os.kiosk_user import (
    KioskUserConfigurator, KioskUserError, create_kiosk_user_plan,
)
from xaac_thin_client_os.thin_client_launcher import (
    ThinClientLauncherConfigurator, ThinClientLauncherError, create_thin_client_launcher_plan,
)
from xaac_thin_client_os.session_supervisor import (
    SessionSupervisorConfigurator, SessionSupervisorError, create_session_supervisor_plan,
)
from xaac_thin_client_os.display_layout import (
    DisplayLayoutConfigurator, DisplayLayoutError, create_display_layout_plan,
)
from xaac_thin_client_os.graphical_session_validation import (
    GraphicalSessionValidationConfigurator, GraphicalSessionValidationError,
    create_graphical_session_validation_plan,
)
from xaac_thin_client_os.kiosk_restrictions import (
    KioskRestrictionConfigurator, KioskRestrictionError, create_kiosk_restriction_plan,
)
from xaac_thin_client_os.shortcut_lockdown import (
    ShortcutLockdownConfigurator, ShortcutLockdownError, create_shortcut_lockdown_plan,
)
from xaac_thin_client_os.terminal_lockdown import (
    TerminalLockdownConfigurator, TerminalLockdownError, create_terminal_lockdown_plan,
)
from xaac_thin_client_os.tty_control import (
    TtyControlConfigurator, TtyControlError, create_tty_control_plan,
)
from xaac_thin_client_os.kiosk_filesystem import (
    KioskFilesystemConfigurator, KioskFilesystemError, create_kiosk_filesystem_plan,
)
from xaac_thin_client_os.local_device_control import (
    LocalDeviceControlConfigurator, LocalDeviceControlError, create_local_device_control_plan,
)
from xaac_thin_client_os.power_action_control import (
    PowerActionControlConfigurator, PowerActionControlError, create_power_action_control_plan,
)
from xaac_thin_client_os.xaac_thin_client_package import (
    XaacThinClientPackageError, XaacThinClientPackageInstaller,
    create_xaac_thin_client_package_plan,
)
from xaac_thin_client_os.xaac_agent_package import (
    XaacAgentPackageError, XaacAgentInstaller, create_xaac_agent_plan,
)
from xaac_thin_client_os.security_policy import (
    SecurityPolicyError, SecurityPolicyInstaller, create_security_policy_plan,
)
from xaac_thin_client_os.account_permissions import (
    AccountPermissionsError, AccountPermissionsInstaller, create_account_permissions_plan,
)
from xaac_thin_client_os.systemd_hardening import (
    SystemdHardeningError, SystemdHardeningInstaller, create_systemd_hardening_plan,
)
from xaac_thin_client_os.apparmor_configuration import (
    AppArmorError, AppArmorInstaller, create_apparmor_plan,
)
from xaac_thin_client_os.kernel_hardening import (
    KernelHardeningError, KernelHardeningInstaller, create_kernel_hardening_plan,
)
from xaac_thin_client_os.file_integrity import (
    FileIntegrityError, FileIntegrityManager, create_file_integrity_plan,
)
from xaac_thin_client_os.package_signing import (
    PackageSigningError, PackageSigningInstaller, create_package_signing_plan,
)
from xaac_thin_client_os.secure_boot_tpm import (
    SecureBootTpmError, SecureBootTpmInstaller, create_secure_boot_tpm_plan,
)
from xaac_thin_client_os.xaac_apt_repository import (
    XaacAptRepositoryError, XaacAptRepositoryInstaller, create_xaac_apt_repository_plan,
)
from xaac_thin_client_os.update_model import (
    UpdateModelError,
    UpdateModelInstaller,
    create_update_model_plan,
    load_update_model,
    resolve_update_channel,
)
from xaac_thin_client_os.update_release_manifest import (
    UpdateReleaseManifestError,
    build_release_manifest,
    write_release_manifest,
)
from xaac_thin_client_os.recovery_model import (
    RecoveryModelError, RecoveryModelInstaller, create_recovery_model_plan,
)
from xaac_thin_client_os.local_recovery import (
    LocalRecoveryError, LocalRecoveryInstaller, create_local_recovery_plan,
)
from xaac_thin_client_os.recovery_partition import (
    RecoveryPartitionError, RecoveryPartitionInstaller, create_recovery_partition_plan,
)
from xaac_thin_client_os.factory_reset import (
    FactoryResetError, FactoryResetInstaller, create_factory_reset_plan,
)
from xaac_thin_client_os.usb_recovery import (
    UsbRecoveryError, UsbRecoveryInstaller, create_usb_recovery_plan,
)
from xaac_thin_client_os.pxe_recovery import (
    PxeRecoveryError, PxeRecoveryInstaller, create_pxe_recovery_plan,
)
from xaac_thin_client_os.iso_builder import (
    IsoBuilder, IsoBuilderError, create_iso_build_plan,
)
from xaac_thin_client_os.img_builder import (
    ImgBuilder, ImgBuilderError, create_img_build_plan,
)
from xaac_thin_client_os.pxe_builder import (
    PxeBuilder, PxeBuilderError, create_pxe_build_plan,
)
from xaac_thin_client_os.installer_builder import (
    InstallerBuilder, InstallerBuilderError, create_installer_build_plan,
)
from xaac_thin_client_os.mass_cloning import (
    MassCloningBuilder, MassCloningError, create_mass_cloning_plan,
)
from xaac_thin_client_os.image_test_suite import (
    ImageTestSuiteBuilder, ImageTestSuiteError, create_image_test_suite_plan,
)
from xaac_thin_client_os.hardware_final_tests import (
    HardwareFinalTestsBuilder, HardwareFinalTestsError, create_hardware_final_tests_plan,
)
from xaac_thin_client_os.performance_stability import (
    PerformanceStabilityBuilder, PerformanceStabilityError, create_performance_stability_plan,
)
from xaac_thin_client_os.documentation import (
    DocumentationBuilder, DocumentationError, create_documentation_plan,
)
from xaac_thin_client_os.production_packaging import (
    ProductionPackagingBuilder, ProductionPackagingError, create_production_packaging_plan,
)
from xaac_thin_client_os.release_candidate import (
    ReleaseCandidateBuilder, ReleaseCandidateError, create_release_candidate_plan,
)
from xaac_thin_client_os.final_release import (
    FinalReleaseBuilder, FinalReleaseError, create_final_release_plan,
)
from xaac_thin_client_os.application_recovery import (
    ApplicationRecoveryError, ApplicationRecoveryInstaller, create_application_recovery_plan,
)
from xaac_thin_client_os.package_repair import (
    PackageRepairError, PackageRepairInstaller, create_package_repair_plan,
)
from xaac_thin_client_os.update_service import (
    UpdateServiceError, UpdateServiceInstaller, create_update_service_plan,
)
from xaac_thin_client_os.update_verification import (
    UpdateVerificationError, UpdateVerificationInstaller, create_update_verification_plan,
)
from xaac_thin_client_os.transactional_update import (
    TransactionalUpdateError, TransactionalUpdateInstaller, create_transactional_update_plan,
)
from xaac_thin_client_os.package_rollback import (
    PackageRollbackError, PackageRollbackInstaller, create_package_rollback_plan,
)
from xaac_thin_client_os.update_rings import (
    UpdateRingsError, UpdateRingsInstaller, create_update_rings_plan,
)
from xaac_thin_client_os.update_sources import (
    UpdateSourcesError, UpdateSourcesInstaller, create_update_sources_plan,
)
from xaac_thin_client_os.device_identity import (
    DeviceIdentityError, DeviceIdentityManager,
)
from xaac_thin_client_os.first_boot import FirstBootError, FirstBootInstaller
from xaac_thin_client_os.local_integration import LocalIntegrationError, LocalIntegrationConfigurator
from xaac_thin_client_os.policy_application import PolicyApplicationError, PolicyApplicationManager
from xaac_thin_client_os.device_inventory import DeviceInventoryCollector, DeviceInventoryError
from xaac_thin_client_os.xms_enrollment import XmsEnrollmentError, XmsEnrollmentManager
from xaac_thin_client_os.network_manager import (
    NetworkManagerConfigurator, NetworkManagerError, create_network_manager_plan,
)
from xaac_thin_client_os.ip_addressing import (
    IpAddressingError, IpAddressingManager, IpAddressingRequest, create_ip_addressing_plan,
)
from xaac_thin_client_os.network_services import (
    NetworkServicesError, NetworkServicesManager, NetworkServicesRequest, create_network_services_plan,
)
from xaac_thin_client_os.vlan_configuration import (
    VlanConfigurationError, VlanManager, VlanRequest, create_vlan_plan,
)
from xaac_thin_client_os.ieee8021x_configuration import (
    Ieee8021xError, Ieee8021xManager, Ieee8021xRequest, create_ieee8021x_plan,
)
from xaac_thin_client_os.local_admin import (
    LocalAdminError, LocalAdminManager, LocalAdminRequest, create_local_admin_plan,
)
from xaac_thin_client_os.audio_support import (
    AudioConfigurator, AudioDetector, AudioSupportError, compare_audio,
    create_audio_configuration_plan, load_audio_profile, write_audio_report,
)
from xaac_thin_client_os.power_thermal import (PowerConfigurator, PowerDetector, PowerThermalError, compare_power, create_power_configuration_plan, load_power_profile, write_power_report)
from xaac_thin_client_os.resource_optimization import (ResourceConfigurator, ResourceDetector, ResourceOptimizationError, compare_resources, create_resource_configuration_plan, load_resource_profile, write_resource_report)
from xaac_thin_client_os.usb_peripherals import (
    UsbConfigurator, UsbDetector, UsbPeripheralError, compare_usb,
    create_usb_configuration_plan, load_usb_profile, write_usb_report,
)
from xaac_thin_client_os.ethernet_support import (
    EthernetConfigurator, EthernetDetector, EthernetSupportError, compare_ethernet,
    create_ethernet_configuration_plan, load_ethernet_profile, write_ethernet_report,
)
from xaac_thin_client_os.hardware_inventory import (
    HardwareDetector, HardwareInventoryError, compare_hardware, load_hardware_profile,
    write_hardware_report,
)
from xaac_thin_client_os.firewall_configuration import (
    FirewallConfigurationError, FirewallConfigurator, create_firewall_configuration_plan,
)
from xaac_thin_client_os.kernel_initramfs import (
    KernelInitramfsConfigurator,
    KernelInitramfsError,
    create_kernel_initramfs_plan,
)
from xaac_thin_client_os.manifest import create_manifest, finalize_manifest
from xaac_thin_client_os.localization import (
    LocalizationConfigurator, LocalizationError, create_localization_plan,
)
from xaac_thin_client_os.metadata import PROJECT_NAME, __version__
from xaac_thin_client_os.network_configuration import (
    NetworkConfigurationError, NetworkConfigurator, create_network_configuration_plan,
)
from xaac_thin_client_os.partitioning import (
    PartitionConfigurator, PartitioningError, create_partition_plan,
)
from xaac_thin_client_os.package_installation import (
    PackageInstallationError,
    PackageInstaller,
    create_package_installation_plan,
)
from xaac_thin_client_os.packages import resolve_packages
from xaac_thin_client_os.runtime import UnsupportedPythonError, ensure_supported_python
from xaac_thin_client_os.ssh_configuration import (
    SshConfigurationError,
    SshConfigurator,
    create_ssh_configuration_plan,
)
from xaac_thin_client_os.systemd_configuration import (
    SystemdConfigurationError, SystemdConfigurator, create_systemd_configuration_plan,
)
from xaac_thin_client_os.system_configuration import (
    SystemConfigurationError,
    SystemConfigurator,
    create_system_configuration_plan,
)
from xaac_thin_client_os.templates import TemplateError, TemplateRenderer
from xaac_thin_client_os.uefi_boot import (
    UefiBootConfigurator, UefiBootError, create_uefi_boot_plan,
)
from xaac_thin_client_os.user_configuration import (
    UserConfigurationError,
    UserConfigurator,
    create_user_configuration_plan,
)
from xaac_thin_client_os.workspace import WorkspaceError, WorkspaceLockedError, WorkspaceManager


def build_parser() -> argparse.ArgumentParser:
    """Build the phase 1.3 command-line parser."""
    parser = argparse.ArgumentParser(prog="xaac-os", description=PROJECT_NAME)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Arrel del projecte (per defecte, el directori actual)",
    )
    parser.add_argument("--json", action="store_true", help="Emet una resposta JSON")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("version", help="Mostra la versió del projecte")
    subparsers.add_parser("check-python", help="Comprova la versió de Python")
    subparsers.add_parser("validate", help="Valida tota la configuració del constructor")
    subparsers.add_parser("inspect", help="Mostra un resum de la configuració efectiva")
    hardware = subparsers.add_parser("inspect-hardware", help="Detecta i valida el maquinari Wyse 3040")
    hardware.add_argument("--report", type=Path, help="Escriu també l'informe JSON en aquesta ruta")
    emmc = subparsers.add_parser("inspect-emmc", help="Detecta i valida l'eMMC del Wyse 3040")
    emmc.add_argument("--report", type=Path, help="Escriu també l'informe JSON en aquesta ruta")
    configure_emmc = subparsers.add_parser("configure-emmc", help="Configura controladors i TRIM de l'eMMC")
    configure_emmc.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    graphics = subparsers.add_parser("inspect-graphics", help="Detecta i valida els gràfics Intel del Wyse 3040")
    graphics.add_argument("--report", type=Path, help="Escriu també l'informe JSON en aquesta ruta")
    configure_graphics = subparsers.add_parser("configure-graphics", help="Configura el controlador Intel i915")
    configure_graphics.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_stack = subparsers.add_parser("configure-graphical-stack", help="Configura Wayland, X11, Mesa i GTK 4")
    configure_stack.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_compositor = subparsers.add_parser("configure-compositor", help="Configura labwc i el fallback X11 controlat")
    configure_compositor.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_session_manager = subparsers.add_parser("configure-session-manager", help="Configura greetd i la sessió dedicada xaac-kiosk")
    configure_session_manager.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_kiosk_user = subparsers.add_parser("configure-kiosk-user", help="Configura el compte dedicat xaac-kiosk")
    configure_kiosk_user.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_launcher = subparsers.add_parser("configure-thin-client-launcher", help="Configura el llançament de XAAC Thin Client")
    configure_launcher.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_supervisor = subparsers.add_parser("configure-session-supervisor", help="Configura la supervisió de la sessió XAAC")
    configure_supervisor.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_display = subparsers.add_parser("configure-display-layout", help="Configura multimonitor, escalat i FreeRDP")
    configure_display.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    validate_graphical = subparsers.add_parser("validate-graphical-session", help="Configura la validació completa de la sessió gràfica")
    validate_graphical.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_restrictions = subparsers.add_parser("configure-kiosk-restrictions", help="Genera el model de restriccions del mode quiosc")
    configure_restrictions.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_shortcuts = subparsers.add_parser("configure-shortcut-lockdown", help="Bloqueja les dreceres de la sessió de quiosc")
    configure_shortcuts.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_terminals = subparsers.add_parser("configure-terminal-lockdown", help="Bloqueja terminals, llançadors, URI i PATH del quiosc")
    configure_terminals.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_ttys = subparsers.add_parser("configure-tty-control", help="Controla els TTY del quiosc i reserva el TTY administratiu")
    configure_ttys.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_filesystem = subparsers.add_parser("configure-kiosk-filesystem", help="Configura el sistema de fitxers efímer del quiosc")
    configure_filesystem.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_devices = subparsers.add_parser("configure-local-device-control", help="Controla USB, emmagatzematge i perifèrics locals del quiosc")
    configure_devices.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_power_actions = subparsers.add_parser("configure-power-action-control", help="Controla apagada, reinici i recuperació del quiosc")
    configure_power_actions.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    install_xaac_client = subparsers.add_parser("install-xaac-thin-client", help="Valida i instal·la el paquet Debian de XAAC Thin Client")
    install_xaac_client.add_argument("--dry-run", action="store_true", help="Valida i planifica sense instal·lar el paquet")
    install_xaac_agent = subparsers.add_parser("install-xaac-agent", help="Instal·la i configura XAAC Thin Client Agent")
    install_xaac_agent.add_argument("--dry-run", action="store_true", help="Valida i planifica sense modificar el rootfs")
    security_policy = subparsers.add_parser("configure-security-policy", help="Instal·la la política base de seguretat i el model d'amenaces")
    security_policy.add_argument("--dry-run", action="store_true")
    account_permissions = subparsers.add_parser("configure-account-permissions", help="Aplica la política d'usuaris, grups i permisos sensibles")
    account_permissions.add_argument("--dry-run", action="store_true")
    systemd_hardening = subparsers.add_parser("configure-systemd-hardening", help="Aplica el hardening de serveis systemd")
    systemd_hardening.add_argument("--dry-run", action="store_true")
    apparmor = subparsers.add_parser("configure-apparmor", help="Instal·la i activa els perfils AppArmor de XAAC")
    apparmor.add_argument("--dry-run", action="store_true")
    kernel_hardening = subparsers.add_parser("configure-kernel-hardening", help="Aplica el hardening del kernel i de la xarxa")
    kernel_hardening.add_argument("--dry-run", action="store_true")
    file_integrity = subparsers.add_parser("configure-file-integrity", help="Crea el manifest i activa la verificació d’integritat")
    file_integrity.add_argument("--dry-run", action="store_true")
    verify_integrity = subparsers.add_parser("verify-file-integrity", help="Comprova o repara els fitxers monitorats")
    verify_integrity.add_argument("--repair", action="store_true")
    package_signing = subparsers.add_parser("configure-package-signing", help="Configura la confiança i verificació dels paquets XAAC")
    package_signing.add_argument("--dry-run", action="store_true")
    secure_boot_tpm = subparsers.add_parser("configure-secure-boot-tpm", help="Configura la política i diagnòstic de Secure Boot i TPM")
    secure_boot_tpm.add_argument("--dry-run", action="store_true")
    update_model = subparsers.add_parser("configure-update-model", help="Configura el model declaratiu d’actualitzacions")
    update_model.add_argument("--dry-run", action="store_true")
    update_manifest = subparsers.add_parser(
        "create-update-manifest",
        help="Genera el manifest SHA-256 d'un release XAAC sense instal·lar-lo",
    )
    update_manifest.add_argument("--target-os-version")
    update_manifest.add_argument(
        "--channel",
        choices=("laboratory", "pilot", "production"),
    )
    update_manifest.add_argument("--minimum-installed-os-version")
    update_manifest.add_argument(
        "--output",
        default=".build/artifacts/xaac-update-manifest.json",
    )
    recovery_model = subparsers.add_parser("configure-recovery-model", help="Configura el model declaratiu d’estats de recuperació")
    recovery_model.add_argument("--dry-run", action="store_true")
    application_recovery = subparsers.add_parser("configure-application-recovery", help="Configura la recuperació del client i de la sessió")
    application_recovery.add_argument("--dry-run", action="store_true")
    package_repair = subparsers.add_parser("configure-package-repair", help="Configura la comprovació i reparació segura de paquets")
    package_repair.add_argument("--dry-run", action="store_true")
    local_recovery = subparsers.add_parser("configure-local-recovery", help="Configura el mode de recuperació local autenticat")
    local_recovery.add_argument("--dry-run", action="store_true")
    recovery_partition = subparsers.add_parser("configure-recovery-partition", help="Configura la partició local de recuperació protegida")
    recovery_partition.add_argument("--dry-run", action="store_true")
    factory_reset = subparsers.add_parser("configure-factory-reset", help="Configura el factory reset local, confirmat i auditable")
    factory_reset.add_argument("--dry-run", action="store_true")
    usb_recovery = subparsers.add_parser("configure-usb-recovery", help="Configura la recuperació mitjançant USB signat")
    usb_recovery.add_argument("--dry-run", action="store_true")
    pxe_recovery = subparsers.add_parser("configure-pxe-recovery", help="Configura la recuperació PXE i remota autoritzada per XMS")
    pxe_recovery.add_argument("--dry-run", action="store_true")
    iso_builder = subparsers.add_parser("build-iso", help="Prepara el constructor de la ISO híbrida de producció")
    iso_builder.add_argument("--dry-run", action="store_true")
    img_builder = subparsers.add_parser("build-img", help="Prepara el constructor de la imatge IMG directa")
    img_builder.add_argument("--dry-run", action="store_true")
    pxe_builder = subparsers.add_parser("build-pxe", help="Prepara el paquet PXE de producció")
    pxe_builder.add_argument("--dry-run", action="store_true")
    installer_builder = subparsers.add_parser("build-installer", help="Prepara l'instal·lador de producció")
    installer_builder.add_argument("--dry-run", action="store_true")
    cloning_builder = subparsers.add_parser("build-cloning", help="Prepara la clonació massiva de la imatge mestra")
    cloning_builder.add_argument("--dry-run", action="store_true")
    image_tests = subparsers.add_parser("build-image-tests", help="Prepara les proves automatitzades de la imatge")
    image_tests.add_argument("--dry-run", action="store_true")
    hardware_tests = subparsers.add_parser("build-hardware-tests", help="Prepara les proves finals de maquinari")
    hardware_tests.add_argument("--dry-run", action="store_true")
    performance_tests = subparsers.add_parser("build-performance-tests", help="Prepara les proves de rendiment i estabilitat")
    performance_tests.add_argument("--dry-run", action="store_true")
    documentation = subparsers.add_parser("build-documentation", help="Valida i prepara la documentació de producció")
    documentation.add_argument("--dry-run", action="store_true")
    production_packaging = subparsers.add_parser("build-production-packaging", help="Prepara paquets i repositoris de producció")
    production_packaging.add_argument("--dry-run", action="store_true")
    release_candidate = subparsers.add_parser("build-release-candidate", help="Prepara i congela la release candidate")
    release_candidate.add_argument("--dry-run", action="store_true")
    final_release = subparsers.add_parser("build-final-release", help="Prepara la release estable 1.0.0")
    final_release.add_argument("--dry-run", action="store_true")
    apt_repository = subparsers.add_parser("configure-xaac-apt-repository", help="Configura l’estructura del repositori APT XAAC")
    apt_repository.add_argument("--dry-run", action="store_true")
    update_service = subparsers.add_parser("configure-update-service", help="Configura el servei de comprovació, descàrrega i staging")
    update_service.add_argument("--dry-run", action="store_true")
    update_verification = subparsers.add_parser("configure-update-verification", help="Configura la verificació d’actualitzacions en staging")
    update_verification.add_argument("--dry-run", action="store_true")
    transactional_update = subparsers.add_parser("configure-transactional-update", help="Configura la instal·lació transaccional d’actualitzacions")
    transactional_update.add_argument("--dry-run", action="store_true")
    package_rollback = subparsers.add_parser("configure-package-rollback", help="Configura el rollback segur de paquets")
    package_rollback.add_argument("--dry-run", action="store_true")
    update_rings = subparsers.add_parser("configure-update-rings", help="Configura el desplegament progressiu per anells")
    update_rings.add_argument("--dry-run", action="store_true")
    update_sources = subparsers.add_parser("configure-update-sources", help="Configura les fonts d’actualització XMS i USB")
    update_sources.add_argument("--dry-run", action="store_true")
    device_identity = subparsers.add_parser("configure-device-identity", help="Genera o valida la identitat persistent del dispositiu")
    device_identity.add_argument("--dry-run", action="store_true", help="Planifica la identitat sense escriure-la")
    first_boot = subparsers.add_parser("configure-first-boot", help="Configura el servei idempotent de primer inici")
    local_integration = subparsers.add_parser("configure-local-integration", help="Configura el contracte local OS-Agent")
    local_integration.add_argument("--dry-run", action="store_true", help="Planifica el contracte local sense modificar el rootfs")
    policies = subparsers.add_parser("configure-policy-application", help="Configura l'aplicació transaccional de polítiques")
    policies.add_argument("--dry-run", action="store_true", help="Planifica la configuració sense modificar el rootfs")
    inventory = subparsers.add_parser("collect-device-inventory", help="Recull l'inventari complet del dispositiu")
    inventory.add_argument("--dry-run", action="store_true", help="Planifica la recollida sense modificar el rootfs")
    enrollment = subparsers.add_parser("configure-xms-enrollment", help="Configura l'enrolament segur del dispositiu en XMS")
    enrollment.add_argument("--dry-run", action="store_true", help="Planifica l'enrolament sense modificar el rootfs")
    network_manager = subparsers.add_parser("configure-network-manager", help="Configura el gestor de xarxa definitiu i la integració amb l'Agent")
    network_manager.add_argument("--dry-run", action="store_true", help="Planifica el gestor sense modificar el rootfs")
    ip_addressing = subparsers.add_parser("configure-ip-addressing", help="Configura DHCP o IPv4 estàtica de manera transaccional")
    ip_addressing.add_argument("--source", choices=("local", "remote"), default="local", help="Origen de la configuració")
    ip_addressing.add_argument("--mode", choices=("dhcp", "static"), default="dhcp", help="Mode d'adreçament")
    ip_addressing.add_argument("--address", help="IPv4 estàtica amb prefix")
    ip_addressing.add_argument("--gateway", help="Passarel·la IPv4")
    ip_addressing.add_argument("--dns", action="append", default=[], help="Servidor DNS; es pot repetir")
    ip_addressing.add_argument("--rollback", action="store_true", help="Restaura l'última configuració vàlida")
    ip_addressing.add_argument("--dry-run", action="store_true", help="Valida i planifica sense escriure")
    network_services = subparsers.add_parser("configure-network-services", help="Configura DNS, NTP i proxy de manera transaccional")
    network_services.add_argument("--source", choices=("local", "remote"), default="local", help="Origen de la configuració")
    network_services.add_argument("--dns", action="append", default=[], help="Servidor DNS; es pot repetir")
    network_services.add_argument("--domain", action="append", default=[], help="Domini de cerca; es pot repetir")
    network_services.add_argument("--ntp", action="append", default=[], help="Servidor NTP; es pot repetir")
    network_services.add_argument("--proxy", help="Proxy HTTP/HTTPS")
    network_services.add_argument("--no-proxy", action="append", default=[], help="Excepció de proxy; es pot repetir")
    network_services.add_argument("--rollback", action="store_true", help="Restaura la configuració anterior")
    network_services.add_argument("--dry-run", action="store_true", help="Valida i planifica sense escriure")
    vlan = subparsers.add_parser("configure-vlan", help="Configura una VLAN 802.1Q de manera transaccional")
    vlan.add_argument("--source", choices=("local", "remote"), default="local")
    vlan.add_argument("--vlan-id", type=int, required=True)
    vlan.add_argument("--name")
    vlan.add_argument("--parent", default="en*")
    vlan.add_argument("--mode", choices=("dhcp", "static"), default="dhcp")
    vlan.add_argument("--address")
    vlan.add_argument("--gateway")
    vlan.add_argument("--dns", action="append", default=[])
    vlan.add_argument("--rollback", action="store_true")
    vlan.add_argument("--dry-run", action="store_true")
    ieee = subparsers.add_parser("configure-ieee8021x", help="Configura IEEE 802.1X cablejat de manera segura")
    ieee.add_argument("--source", choices=("local", "remote"), default="local")
    ieee.add_argument("--interface", default="en*")
    ieee.add_argument("--eap", choices=("tls", "peap"), default="tls")
    ieee.add_argument("--identity", required=True)
    ieee.add_argument("--anonymous-identity")
    ieee.add_argument("--ca-certificate", required=True)
    ieee.add_argument("--client-certificate")
    ieee.add_argument("--private-key")
    ieee.add_argument("--private-key-password")
    ieee.add_argument("--password")
    ieee.add_argument("--rollback", action="store_true")
    ieee.add_argument("--dry-run", action="store_true")
    local_admin = subparsers.add_parser("configure-local-admin", help="Configura el perfil administrador local")
    local_admin.add_argument("--source", choices=("local", "remote"), default="local")
    local_admin.add_argument("--username", default="xaac-admin")
    local_admin.add_argument("--password-hash")
    local_admin.add_argument("--no-force-password-change", action="store_true")
    local_admin.add_argument("--rollback", action="store_true")
    local_admin.add_argument("--dry-run", action="store_true")
    first_boot.add_argument("--dry-run", action="store_true", help="Planifica el servei sense modificar el rootfs")
    ethernet = subparsers.add_parser("inspect-ethernet", help="Detecta i valida Ethernet del Wyse 3040")
    ethernet.add_argument("--report", type=Path, help="Escriu també l'informe JSON en aquesta ruta")
    configure_ethernet = subparsers.add_parser("configure-ethernet", help="Configura Ethernet amb systemd-networkd")
    configure_ethernet.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    configure_ethernet.add_argument("--mode", choices=("dhcp", "static"), help="Mode d'adreçament")
    configure_ethernet.add_argument("--address", help="IPv4 estàtica amb prefix, per exemple 192.0.2.10/24")
    configure_ethernet.add_argument("--gateway", help="Passarel·la IPv4")
    configure_ethernet.add_argument("--dns", action="append", default=[], help="Servidor DNS; es pot repetir")
    audio = subparsers.add_parser("inspect-audio", help="Detecta i valida l'àudio del Wyse 3040")
    audio.add_argument("--report", type=Path, help="Escriu també l'informe JSON en aquesta ruta")
    configure_audio = subparsers.add_parser("configure-audio", help="Configura ALSA i PipeWire")
    configure_audio.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    usb = subparsers.add_parser("inspect-usb", help="Detecta i valida USB i perifèrics del Wyse 3040")
    usb.add_argument("--report", type=Path, help="Guarda l'informe JSON")
    configure_usb = subparsers.add_parser("configure-usb", help="Configura mòduls i política USB")
    configure_usb.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    power = subparsers.add_parser("inspect-power", help="Detecta energia, temperatura i watchdog")
    power.add_argument("--report", type=Path, help="Guarda l'informe JSON")
    configure_power = subparsers.add_parser("configure-power", help="Configura energia, suspensió i watchdog")
    configure_power.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    resources = subparsers.add_parser("inspect-resources", help="Detecta ús de RAM, zram, disc i journald")
    resources.add_argument("--report", type=Path, help="Guarda l'informe JSON")
    configure_resources = subparsers.add_parser("configure-resources", help="Optimitza RAM i escriptures de disc")
    configure_resources.add_argument("--dry-run", action="store_true", help="Planifica els canvis sense modificar el rootfs")
    subparsers.add_parser("prepare", help="Comprova que el projecte està preparat")
    subparsers.add_parser("build", help="Executa la validació prèvia de construcció")
    bootstrap = subparsers.add_parser("bootstrap", help="Crea el sistema Debian 13 minimal")
    bootstrap.add_argument(
        "--dry-run", action="store_true", help="Mostra i registra l’ordre sense executar-la"
    )
    bootstrap.add_argument(
        "--keep-partial",
        action="store_true",
        help="Conserva el rootfs parcial si debootstrap falla",
    )
    apt_configure = subparsers.add_parser(
        "configure-apt", help="Configura els repositoris APT del rootfs actual"
    )
    apt_configure.add_argument(
        "--dry-run", action="store_true", help="Registra la configuració sense modificar el rootfs"
    )
    install_packages = subparsers.add_parser(
        "install-packages", help="Instal·la el sistema base dins del rootfs actual"
    )
    install_packages.add_argument(
        "--dry-run", action="store_true", help="Registra les ordres sense executar APT"
    )
    configure_kernel = subparsers.add_parser(
        "configure-kernel", help="Configura el kernel i genera l'initramfs"
    )
    configure_kernel.add_argument(
        "--dry-run", action="store_true", help="Registra el pla sense modificar el rootfs"
    )
    configure_uefi = subparsers.add_parser(
        "configure-uefi", help="Instal·la i configura GRUB per a arrencada UEFI"
    )
    configure_uefi.add_argument(
        "--dry-run", action="store_true", help="Registra el pla sense modificar el rootfs"
    )
    configure_partitions = subparsers.add_parser(
        "configure-partitions", help="Configura l'esquema GPT inicial del disc"
    )
    configure_partitions.add_argument("--device", type=Path, required=True, help="Dispositiu de bloc de destinació")
    configure_partitions.add_argument("--dry-run", action="store_true", help="Registra el pla sense modificar el disc")
    configure_partitions.add_argument("--confirm-destructive", action="store_true", help="Confirma explícitament la destrucció del disc")
    configure_systemd = subparsers.add_parser(
        "configure-systemd", help="Configura el sistema base systemd del rootfs"
    )
    configure_systemd.add_argument(
        "--dry-run", action="store_true", help="Registra el pla sense modificar el rootfs"
    )
    configure_localization = subparsers.add_parser(
        "configure-localization", help="Configura locale, teclat, zona horària i consola"
    )
    configure_localization.add_argument(
        "--dry-run", action="store_true", help="Registra el pla sense modificar el rootfs"
    )
    build_rootfs = subparsers.add_parser(
        "build-rootfs", help="Construeix només el rootfs reutilitzable per ISO, IMG i PXE"
    )
    build_rootfs.add_argument(
        "--dry-run", action="store_true", help="Planifica el rootfs sense modificar-lo"
    )
    build_image = subparsers.add_parser(
        "build-image", help="Genera una imatge de disc completa i arrencable"
    )
    build_image.add_argument(
        "--dry-run", action="store_true", help="Planifica la imatge sense crear artefactes"
    )
    configure_system = subparsers.add_parser(
        "configure-system", help="Configura identitat, locale i zona horària del rootfs"
    )
    configure_system.add_argument(
        "--dry-run", action="store_true", help="Registra els canvis sense modificar el rootfs"
    )
    configure_users = subparsers.add_parser(
        "configure-users", help="Configura els usuaris i grups inicials del rootfs"
    )
    configure_users.add_argument(
        "--dry-run", action="store_true", help="Registra els canvis sense modificar el rootfs"
    )
    configure_network = subparsers.add_parser("configure-network", help="Configura la xarxa mínima del rootfs")
    configure_network.add_argument("--dry-run", action="store_true", help="Registra els canvis sense modificar el rootfs")
    configure_ssh = subparsers.add_parser("configure-ssh", help="Configura i endureix el servidor SSH")
    configure_ssh.add_argument("--dry-run", action="store_true", help="Registra els canvis sense modificar el rootfs")
    configure_firewall = subparsers.add_parser("configure-firewall", help="Configura el tallafoc nftables del rootfs")
    configure_firewall.add_argument("--dry-run", action="store_true", help="Registra els canvis sense modificar el rootfs")
    clean = subparsers.add_parser("clean", help="Elimina artefactes generats coneguts")
    clean.add_argument("--force", action="store_true", help="Confirma l'eliminació de .build")
    return parser


def _emit(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(payload["message"])


def _configuration_summary(root: Path) -> dict[str, object]:
    configuration = load_project_configuration(root)
    resolved = resolve_packages(root, configuration)
    return {
        "project": configuration.build.project,
        "version": configuration.build.version,
        "profile": configuration.build.profile,
        "architecture": configuration.build.architecture.value,
        "channel": configuration.build.channel.value,
        "image_formats": [item.value for item in configuration.build.image.formats],
        "image_size_mib": configuration.build.image.size_mib,
        "repositories": [repository.name for repository in configuration.repositories],
        "package_count": len(resolved.packages),
        "packages": list(resolved.packages),
        "excluded_packages": list(resolved.excluded),
        "profile_chain": list(resolved.profile_chain),
        "package_manifest": resolved.to_manifest(),
    }


def _validate(root: Path, *, as_json: bool) -> int:
    summary = _configuration_summary(root)
    _emit({"status": "ok", "message": "Configuració vàlida", **summary}, as_json=as_json)
    return 0


def _inspect(root: Path, *, as_json: bool) -> int:
    summary = _configuration_summary(root)
    if as_json:
        _emit({"status": "ok", "message": "Configuració carregada", **summary}, as_json=True)
    else:
        print(f"Projecte: {summary['project']} {summary['version']}")
        print(f"Perfil: {summary['profile']} ({summary['architecture']})")
        print(f"Canal: {summary['channel']}")
        print(f"Imatge: {', '.join(summary['image_formats'])} · {summary['image_size_mib']} MiB")
        print(f"Perfils heretats: {' -> '.join(summary['profile_chain'])}")
        print(f"Paquets efectius: {summary['package_count']}")
        print(f"Llista de paquets: {', '.join(summary['packages'])}")
        print(f"Exclusions: {', '.join(summary['excluded_packages']) or 'cap'}")
        print(f"Repositoris: {', '.join(summary['repositories'])}")
    return 0


def _template_context(root: Path, build_id: str) -> dict[str, object]:
    configuration = load_project_configuration(root)
    resolved = resolve_packages(root, configuration)
    return {
        "project": {"name": configuration.build.project, "version": configuration.build.version},
        "build": {
            "id": build_id,
            "profile": configuration.build.profile,
            "architecture": configuration.build.architecture.value,
            "channel": configuration.build.channel.value,
        },
        "debian": {"suite": configuration.build.debian.suite},
        "image": {
            "size_mib": configuration.build.image.size_mib,
            "output_directory": str(configuration.build.image.output_directory),
        },
        "packages": {"count": len(resolved.packages)},
    }


def _workspace_manifest(root: Path) -> dict[str, object]:
    configuration = load_project_configuration(root)
    resolved = resolve_packages(root, configuration)
    return create_manifest(root, configuration, resolved)


def _prepare(root: Path, *, as_json: bool) -> int:
    _configuration_summary(root)
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.prepare(_workspace_manifest(root))
        rendered = TemplateRenderer(
            root / "templates" / "base", workspace.rendered_dir
        ).render_tree(_template_context(root, workspace.build_id))
        hooks = HookRunner(
            root,
            workspace.logs_dir,
            environment={
                "XAAC_BUILD_ID": workspace.build_id,
                "XAAC_WORKSPACE": str(workspace.run_dir),
                "XAAC_RENDERED_DIR": str(workspace.rendered_dir),
                "XAAC_ARTIFACTS_DIR": str(workspace.artifacts_dir),
                "XAAC_TMP_DIR": str(workspace.temporary_dir),
            },
        ).run_all()
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        final_manifest = finalize_manifest(
            current_manifest,
            rendered_files=(item.destination for item in rendered),
            hook_logs=(item.log_path for item in hooks),
            root=root,
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    payload = {
        "status": "ok",
        "message": f"Espai de treball preparat: {workspace.build_id}",
        "build_id": workspace.build_id,
        "workspace": str(workspace.run_dir.relative_to(root)),
        "manifest": str(workspace.manifest_path.relative_to(root)),
        "rendered_templates": [str(item.destination.relative_to(root)) for item in rendered],
        "executed_hooks": [
            {
                "phase": item.phase.value,
                "name": item.name,
                "log": str(item.log_path.relative_to(root)),
            }
            for item in hooks
        ],
    }
    _emit(payload, as_json=as_json)
    return 0


def _bootstrap(root: Path, *, dry_run: bool, keep_partial: bool, as_json: bool) -> int:
    configuration = load_project_configuration(root)
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.prepare(_workspace_manifest(root))
        plan = create_bootstrap_plan(configuration.build, workspace.rootfs_dir)
        result = BootstrapRunner().execute(
            plan,
            workspace.logs_dir / "debootstrap.log",
            dry_run=dry_run,
            keep_partial=keep_partial,
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["bootstrap"] = {**plan.to_manifest(), "executed": result.executed}
        current_manifest["status"] = "bootstrapped" if result.executed else "bootstrap-planned"
        final_manifest = finalize_manifest(
            current_manifest,
            hook_logs=(result.log_path,),
            root=root,
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    message = (
        f"Debian {plan.suite} minimal creat: {workspace.build_id}"
        if result.executed
        else f"Bootstrap planificat: {workspace.build_id}"
    )
    _emit(
        {
            "status": "ok",
            "message": message,
            "build_id": workspace.build_id,
            "executed": result.executed,
            "rootfs": str(plan.target.relative_to(root)),
            "log": str(result.log_path.relative_to(root)),
            "command": list(plan.command()),
        },
        as_json=as_json,
    )
    return 0


def _configure_apt(root: Path, *, dry_run: bool, as_json: bool) -> int:
    configuration = load_project_configuration(root)
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_apt_configuration_plan(
            workspace.rootfs_dir,
            configuration.repositories,
            configuration.build.architecture.value,
        )
        result = AptConfigurator().execute(
            plan, workspace.logs_dir / "apt-configuration.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["apt"] = {**plan.to_manifest(), "executed": result.executed}
        current_manifest["status"] = "apt-configured" if result.executed else "apt-planned"
        final_manifest = finalize_manifest(
            current_manifest,
            rendered_files=result.files,
            hook_logs=(result.log_path,),
            root=root,
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": (
                f"APT configurat: {workspace.build_id}"
                if result.executed
                else f"Configuració APT planificada: {workspace.build_id}"
            ),
            "build_id": workspace.build_id,
            "executed": result.executed,
            "sources": str(plan.sources_path.relative_to(root)),
            "policy": str(plan.policy_path.relative_to(root)),
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0


def _install_packages(root: Path, *, dry_run: bool, as_json: bool) -> int:
    configuration = load_project_configuration(root)
    resolved = resolve_packages(root, configuration)
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_package_installation_plan(
            workspace.rootfs_dir, resolved.packages, resolved.excluded
        )
        result = PackageInstaller().execute(
            plan, workspace.logs_dir / "package-installation.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["package_installation"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "commands_executed": result.commands_executed,
        }
        current_manifest["status"] = "packages-installed" if result.executed else "packages-planned"
        final_manifest = finalize_manifest(
            current_manifest, hook_logs=(result.log_path,), root=root
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": (
                f"Sistema base instal·lat: {workspace.build_id}"
                if result.executed
                else f"Instal·lació de paquets planificada: {workspace.build_id}"
            ),
            "build_id": workspace.build_id,
            "executed": result.executed,
            "package_count": len(plan.packages),
            "packages": list(plan.packages),
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0



def _configure_kernel(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_kernel_initramfs_plan(
            workspace.rootfs_dir, root / "config/kernel.yaml", allow_missing_versions=dry_run
        )
        result = KernelInitramfsConfigurator().execute(
            plan, workspace.logs_dir / "kernel-initramfs.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["kernel_initramfs"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "commands_executed": result.commands_executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
        }
        current_manifest["status"] = (
            "kernel-initramfs-configured" if result.executed else "kernel-initramfs-planned"
        )
        final_manifest = finalize_manifest(
            current_manifest, hook_logs=(result.log_path,), root=root
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": f"Kernel i initramfs {'configurats' if result.executed else 'planificats'}: {workspace.build_id}",
            "build_id": workspace.build_id,
            "executed": result.executed,
            "kernel_versions": list(plan.kernel_versions),
            "modules": list(plan.modules),
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0


def _configure_uefi(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_uefi_boot_plan(
            workspace.rootfs_dir, root / "config/uefi.yaml", allow_missing_kernel=dry_run
        )
        result = UefiBootConfigurator().execute(
            plan, workspace.logs_dir / "uefi-boot.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["uefi_boot"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "commands_executed": result.commands_executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
        }
        current_manifest["status"] = "uefi-configured" if result.executed else "uefi-planned"
        final_manifest = finalize_manifest(current_manifest, hook_logs=(result.log_path,), root=root)
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": f"Arrencada UEFI {'configurada' if result.executed else 'planificada'}: {workspace.build_id}",
            "build_id": workspace.build_id,
            "executed": result.executed,
            "target": plan.target,
            "bootloader_id": plan.bootloader_id,
            "kernel_versions": list(plan.kernel_versions),
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0


def _configure_partitions(root: Path, *, device: Path, dry_run: bool, confirm_destructive: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_partition_plan(workspace.rootfs_dir, root / "config/partitions.yaml", device)
        result = PartitionConfigurator().execute(
            plan, workspace.logs_dir / "partitioning.log", dry_run=dry_run, confirm_destructive=confirm_destructive
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["partitioning"] = {
            **plan.to_manifest(), "executed": result.executed,
            "commands_executed": result.commands_executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
        }
        current_manifest["status"] = "partitions-configured" if result.executed else "partitions-planned"
        final_manifest = finalize_manifest(current_manifest, rendered_files=result.files_written, hook_logs=(result.log_path,), root=root)
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit({
        "status": "ok",
        "message": f"Esquema de particions {'configurat' if result.executed else 'planificat'}: {workspace.build_id}",
        "build_id": workspace.build_id, "executed": result.executed,
        "device": str(plan.device), "partition_count": len(plan.partitions),
        "log": str(result.log_path.relative_to(root)),
    }, as_json=as_json)
    return 0

def _configure_systemd(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_systemd_configuration_plan(workspace.rootfs_dir, root / "config/systemd.yaml")
        result = SystemdConfigurator().execute(
            plan, workspace.logs_dir / "systemd-configuration.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["systemd_configuration"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
            "links": [str(path.relative_to(root)) for path in result.links_created],
        }
        current_manifest["status"] = "systemd-configured" if result.executed else "systemd-planned"
        final_manifest = finalize_manifest(
            current_manifest, rendered_files=(*result.files_written, *result.links_created),
            hook_logs=(result.log_path,), root=root
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit({
        "status": "ok",
        "message": f"Sistema base systemd {'configurat' if result.executed else 'planificat'}: {workspace.build_id}",
        "build_id": workspace.build_id,
        "executed": result.executed,
        "default_target": plan.default_target,
        "enabled_services": list(plan.enable_services),
        "masked_services": list(plan.mask_services),
        "log": str(result.log_path.relative_to(root)),
    }, as_json=as_json)
    return 0


def _configure_localization(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_localization_plan(workspace.rootfs_dir, root / "config/localization.yaml")
        result = LocalizationConfigurator().execute(
            plan, workspace.logs_dir / "localization.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["localization"] = {
            **plan.to_manifest(), "executed": result.executed,
            "commands_executed": result.commands_executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
        }
        current_manifest["status"] = "localization-configured" if result.executed else "localization-planned"
        final_manifest = finalize_manifest(current_manifest, rendered_files=result.files_written, hook_logs=(result.log_path,), root=root)
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit({"status":"ok", "message": f"Localització i consola {'configurades' if result.executed else 'planificades'}: {workspace.build_id}",
           "build_id":workspace.build_id, "executed":result.executed, "locale":plan.locale,
           "timezone":plan.timezone, "keyboard_layout":plan.keyboard_layout,
           "keyboard_variant":plan.keyboard_variant, "log":str(result.log_path.relative_to(root))}, as_json=as_json)
    return 0


def _configure_system(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_system_configuration_plan(workspace.rootfs_dir, root / "config/system.yaml")
        result = SystemConfigurator().execute(
            plan, workspace.logs_dir / "system-configuration.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["system_configuration"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "commands_executed": result.commands_executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
        }
        current_manifest["status"] = (
            "system-configured" if result.executed else "system-configuration-planned"
        )
        final_manifest = finalize_manifest(
            current_manifest, hook_logs=(result.log_path,), root=root
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": (
                f"Sistema configurat: {workspace.build_id}"
                if result.executed
                else f"Configuració del sistema planificada: {workspace.build_id}"
            ),
            "build_id": workspace.build_id,
            "executed": result.executed,
            "hostname": plan.hostname,
            "timezone": plan.timezone,
            "locale": plan.locale,
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0


def _configure_users(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_user_configuration_plan(workspace.rootfs_dir, root / "config/users.yaml")
        result = UserConfigurator().execute(
            plan, workspace.logs_dir / "user-configuration.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["user_configuration"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "commands_executed": result.commands_executed,
        }
        current_manifest["status"] = (
            "users-configured" if result.executed else "user-configuration-planned"
        )
        final_manifest = finalize_manifest(
            current_manifest, hook_logs=(result.log_path,), root=root
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": (
                f"Usuaris configurats: {workspace.build_id}"
                if result.executed
                else f"Configuració d'usuaris planificada: {workspace.build_id}"
            ),
            "build_id": workspace.build_id,
            "executed": result.executed,
            "groups": [item.name for item in plan.groups],
            "users": [item.name for item in plan.users],
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0



def _configure_network(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_network_configuration_plan(workspace.rootfs_dir, root / "config/network.yaml")
        result = NetworkConfigurator().execute(plan, workspace.logs_dir / "network-configuration.log", dry_run=dry_run)
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["network_configuration"] = {**plan.to_manifest(), "executed": result.executed, "files": [str(path.relative_to(root)) for path in result.files_written]}
        current_manifest["status"] = "network-configured" if result.executed else "network-configuration-planned"
        final_manifest = finalize_manifest(current_manifest, hook_logs=(result.log_path,), root=root)
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit({"status":"ok", "message": f"Xarxa {'configurada' if result.executed else 'planificada'}: {workspace.build_id}", "build_id":workspace.build_id, "executed":result.executed, "backend":"systemd-networkd", "interface_match":plan.interface_match, "log":str(result.log_path.relative_to(root))}, as_json=as_json)
    return 0

def _configure_ssh(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_ssh_configuration_plan(workspace.rootfs_dir, root / "config/ssh.yaml")
        result = SshConfigurator().execute(
            plan, workspace.logs_dir / "ssh-configuration.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["ssh_configuration"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
        }
        current_manifest["status"] = (
            "ssh-configured" if result.executed else "ssh-configuration-planned"
        )
        final_manifest = finalize_manifest(
            current_manifest, hook_logs=(result.log_path,), root=root
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": f"SSH {'configurat' if result.executed else 'planificat'}: {workspace.build_id}",
            "build_id": workspace.build_id,
            "executed": result.executed,
            "port": plan.port,
            "allow_users": list(plan.allow_users),
            "allowed_sources": list(plan.allowed_sources),
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0


def _configure_firewall(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = WorkspaceManager(root)
    with manager:
        workspace = manager.current()
        if workspace is None:
            raise WorkspaceError("No hi ha cap espai de treball actual; executeu primer bootstrap")
        plan = create_firewall_configuration_plan(
            workspace.rootfs_dir, root / "config/firewall.yaml", root / "config/ssh.yaml"
        )
        result = FirewallConfigurator().execute(
            plan, workspace.logs_dir / "firewall-configuration.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["firewall_configuration"] = {
            **plan.to_manifest(),
            "executed": result.executed,
            "files": [str(path.relative_to(root)) for path in result.files_written],
        }
        current_manifest["status"] = (
            "firewall-configured" if result.executed else "firewall-configuration-planned"
        )
        final_manifest = finalize_manifest(current_manifest, hook_logs=(result.log_path,), root=root)
        manager._write_json_atomic(workspace.manifest_path, final_manifest)
    _emit(
        {
            "status": "ok",
            "message": f"Tallafoc {'configurat' if result.executed else 'planificat'}: {workspace.build_id}",
            "build_id": workspace.build_id,
            "executed": result.executed,
            "backend": "nftables",
            "ssh_port": plan.ssh_port,
            "management_sources": list(plan.management_sources_v4 + plan.management_sources_v6),
            "agent_ports": list(plan.agent_tcp_ports + plan.agent_udp_ports),
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0



def _build_image(root: Path, *, dry_run: bool, as_json: bool, rootfs_only: bool = False) -> int:
    """Build a complete image from scratch or reuse a complete current rootfs.

    A real ``build-image`` invocation is intentionally self-contained: when the
    current workspace has no usable rootfs, every required Block 2 step is run
    in one newly prepared workspace.  This avoids depending on a stale
    ``.build/current`` pointer left by tests, dry-runs or previous commands.
    """
    if not dry_run:
        require_build_dependencies()
    configuration = load_project_configuration(root)
    resolved_packages = resolve_packages(root, configuration)
    manager = WorkspaceManager(root)
    pipeline_logs: list[Path] = []
    pipeline_files: list[Path] = []

    with manager:
        workspace = manager.current()
        rootfs_ready = bool(
            workspace is not None
            and (workspace.rootfs_dir / "etc/debian_version").is_file()
            and (workspace.rootfs_dir / "etc/fstab").is_file()
            and any((workspace.rootfs_dir / "boot").glob("vmlinuz-*"))
            and any((workspace.rootfs_dir / "boot").glob("initrd.img-*"))
        )

        if workspace is None or (not dry_run and not rootfs_ready):
            workspace = manager.prepare(_workspace_manifest(root))

        if dry_run:
            # Planning must remain unprivileged and offline.  The empty rootfs
            # directory only gives the image planner a safe workspace path.
            workspace.rootfs_dir.mkdir(parents=True, exist_ok=True)
        elif not rootfs_ready:
            manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))

            bootstrap_plan = create_bootstrap_plan(configuration.build, workspace.rootfs_dir)
            bootstrap_result = BootstrapRunner().execute(
                bootstrap_plan, workspace.logs_dir / "debootstrap.log"
            )
            manifest["bootstrap"] = {**bootstrap_plan.to_manifest(), "executed": True}
            pipeline_logs.append(bootstrap_result.log_path)

            apt_plan = create_apt_configuration_plan(
                workspace.rootfs_dir, configuration.repositories,
                configuration.build.architecture.value,
            )
            apt_result = AptConfigurator().execute(
                apt_plan, workspace.logs_dir / "apt-configuration.log"
            )
            manifest["apt"] = {**apt_plan.to_manifest(), "executed": True}
            pipeline_logs.append(apt_result.log_path)
            pipeline_files.extend(apt_result.files)

            packages_plan = create_package_installation_plan(
                workspace.rootfs_dir, resolved_packages.packages, resolved_packages.excluded
            )
            packages_result = PackageInstaller().execute(
                packages_plan, workspace.logs_dir / "package-installation.log"
            )
            manifest["package_installation"] = {
                **packages_plan.to_manifest(), "executed": True,
                "commands_executed": packages_result.commands_executed,
            }
            pipeline_logs.append(packages_result.log_path)

            system_plan = create_system_configuration_plan(
                workspace.rootfs_dir, root / "config/system.yaml"
            )
            system_result = SystemConfigurator().execute(
                system_plan, workspace.logs_dir / "system-configuration.log"
            )
            manifest["system_configuration"] = {**system_plan.to_manifest(), "executed": True}
            pipeline_logs.append(system_result.log_path)
            pipeline_files.extend(system_result.files_written)

            kernel_plan = create_kernel_initramfs_plan(
                workspace.rootfs_dir, root / "config/kernel.yaml"
            )
            kernel_result = KernelInitramfsConfigurator().execute(
                kernel_plan, workspace.logs_dir / "kernel-initramfs.log"
            )
            manifest["kernel_initramfs"] = {**kernel_plan.to_manifest(), "executed": True}
            pipeline_logs.append(kernel_result.log_path)
            pipeline_files.extend(kernel_result.files_written)

            systemd_plan = create_systemd_configuration_plan(
                workspace.rootfs_dir, root / "config/systemd.yaml"
            )
            systemd_result = SystemdConfigurator().execute(
                systemd_plan, workspace.logs_dir / "systemd-configuration.log"
            )
            manifest["systemd_configuration"] = {**systemd_plan.to_manifest(), "executed": True}
            pipeline_logs.append(systemd_result.log_path)
            pipeline_files.extend((*systemd_result.files_written, *systemd_result.links_created))

            localization_plan = create_localization_plan(
                workspace.rootfs_dir, root / "config/localization.yaml"
            )
            localization_result = LocalizationConfigurator().execute(
                localization_plan, workspace.logs_dir / "localization.log"
            )
            manifest["localization"] = {**localization_plan.to_manifest(), "executed": True}
            pipeline_logs.append(localization_result.log_path)
            pipeline_files.extend(localization_result.files_written)

            partition_plan = create_partition_plan(
                workspace.rootfs_dir, root / "config/partitions.yaml", Path("/dev/loop0")
            )
            PartitionConfigurator._write_atomic(
                partition_plan.fstab_path, partition_plan.fstab_content()
            )
            manifest["partition_layout"] = {
                **partition_plan.to_manifest(), "executed": False,
                "fstab_generated": True,
            }
            pipeline_files.append(partition_plan.fstab_path)

            # La instal·lació de GRUB sobre un dispositiu pertany al constructor
            # d'imatges de disc. Una ISO reutilitza el rootfs però genera la seua
            # pròpia arrencada amb grub-mkrescue, sense grub-install en chroot.
            if not rootfs_only:
                uefi_plan = create_uefi_boot_plan(
                    workspace.rootfs_dir, root / "config/uefi.yaml"
                )
                uefi_result = UefiBootConfigurator().execute(
                    uefi_plan, workspace.logs_dir / "uefi-boot.log"
                )
                manifest["uefi_boot"] = {**uefi_plan.to_manifest(), "executed": True}
                pipeline_logs.append(uefi_result.log_path)
                pipeline_files.extend(uefi_result.files_written)

            manifest["status"] = "rootfs-ready"
            manager._write_json_atomic(workspace.manifest_path, manifest)

        if rootfs_only:
            current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
            current_manifest["status"] = "rootfs-ready"
            final_manifest = finalize_manifest(
                current_manifest, rendered_files=tuple(pipeline_files),
                hook_logs=tuple(pipeline_logs), root=root,
            )
            manager._write_json_atomic(workspace.manifest_path, final_manifest)
            _emit(
                {
                    "status": "ok",
                    "message": f"Rootfs generat: {workspace.build_id}",
                    "build_id": workspace.build_id,
                    "executed": not dry_run,
                    "rootfs": str(workspace.rootfs_dir.relative_to(root)),
                },
                as_json=as_json,
            )
            return 0

        plan = create_bootable_image_plan(
            workspace.rootfs_dir, workspace.artifacts_dir, workspace.temporary_dir,
            root / "config/partitions.yaml", allow_incomplete_rootfs=dry_run,
        )
        result = BootableImageBuilder().execute(
            plan, workspace.logs_dir / "bootable-image.log", dry_run=dry_run
        )
        current_manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current_manifest["bootable_image"] = {
            **plan.to_manifest(), "executed": result.executed,
            "image_sha256": result.image_sha256,
            "compressed_sha256": result.compressed_sha256,
        }
        current_manifest["status"] = "image-built" if result.executed else "image-planned"
        final_manifest = finalize_manifest(
            current_manifest,
            rendered_files=(*pipeline_files, *result.files_written),
            hook_logs=(*pipeline_logs, result.log_path),
            root=root,
        )
        manager._write_json_atomic(workspace.manifest_path, final_manifest)

    _emit(
        {
            "status": "ok",
            "message": f"Imatge {'generada' if result.executed else 'planificada'}: {workspace.build_id}",
            "build_id": workspace.build_id, "executed": result.executed,
            "image": str(plan.image_path.relative_to(root)),
            "compressed_image": str(plan.compressed_path.relative_to(root)),
            "checksum": str(plan.checksum_path.relative_to(root)),
            "log": str(result.log_path.relative_to(root)),
        },
        as_json=as_json,
    )
    return 0



def _inspect_hardware(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    profile = load_hardware_profile(root / "config/hardware.yaml")
    report = compare_hardware(HardwareDetector().detect(), profile)
    if report_path is not None:
        destination = report_path if report_path.is_absolute() else root / report_path
        write_hardware_report(report, destination)
    payload = {
        "status": "ok" if report.compatible else "incompatible",
        "message": (
            "Maquinari compatible amb el perfil Dell Wyse 3040"
            if report.compatible else "El maquinari no compleix el perfil Dell Wyse 3040"
        ),
        **report.to_dict(),
    }
    if as_json:
        _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4


def _inspect_emmc(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    profile = load_emmc_profile(root / "config/emmc.yaml")
    devices, modules = EmmcDetector().detect()
    report = compare_emmc(devices, modules, profile)
    if report_path is not None:
        destination = report_path if report_path.is_absolute() else root / report_path
        write_emmc_report(report, destination)
    payload = {
        "status": "ok" if report.compatible else "incompatible",
        "message": (
            "eMMC compatible amb el perfil Dell Wyse 3040"
            if report.compatible else "L'eMMC no compleix el perfil Dell Wyse 3040"
        ),
        **report.to_dict(),
    }
    if as_json:
        _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4


def _configure_emmc(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_emmc_configuration_plan(workspace.rootfs_dir, root / "config/emmc.yaml")
    result = EmmcConfigurator().execute(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": (
            "Configuració eMMC planificada sense modificar el rootfs"
            if dry_run else "Controladors eMMC i TRIM configurats"
        ),
        "executed": result.executed,
        "files": [str(path) for path in result.files_written],
        "plan": plan.to_manifest(),
    }
    _emit(payload, as_json=as_json)
    return 0


def _inspect_graphics(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    profile = load_graphics_profile(root / "config/graphics.yaml")
    report = compare_graphics(IntelGraphicsDetector().detect(), profile)
    if report_path is not None:
        destination = report_path if report_path.is_absolute() else root / report_path
        write_graphics_report(report, destination)
    payload = {"status": "ok" if report.compatible else "incompatible", "message": "Gràfics Intel compatibles" if report.compatible else "La pila gràfica no compleix el perfil Wyse 3040", **report.to_dict()}
    if as_json:
        _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4


def _configure_graphics(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_graphics_configuration_plan(workspace.rootfs_dir, root / "config/graphics.yaml")
    written = IntelGraphicsConfigurator().execute(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "Configuració gràfica planificada" if dry_run else "Controlador Intel i915 configurat", "executed": not dry_run, "files": [str(path) for path in written], "plan": plan.to_manifest()}, as_json=as_json)
    return 0



def _configure_graphical_stack(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_graphical_stack_plan(
        workspace.rootfs_dir, root / "config/graphical-stack.yaml"
    )
    written = GraphicalStackConfigurator().execute(plan, dry_run=dry_run)
    _emit(
        {
            "status": "planned" if dry_run else "ok",
            "message": (
                "Pila gràfica mínima planificada"
                if dry_run
                else "Pila gràfica mínima configurada"
            ),
            "executed": not dry_run,
            "files": [str(path) for path in written],
            "plan": plan.to_manifest(),
        },
        as_json=as_json,
    )
    return 0


def _configure_compositor(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_compositor_plan(workspace.rootfs_dir, root / "config/compositor.yaml")
    written = CompositorConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Compositor planificat" if dry_run else "Compositor configurat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0


def _configure_session_manager(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_session_manager_plan(workspace.rootfs_dir, root / "config/session-manager.yaml")
    written = SessionManagerConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Gestor de sessió planificat" if dry_run else "Gestor de sessió configurat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0



def _configure_kiosk_user(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_kiosk_user_plan(workspace.rootfs_dir, root / "config/kiosk-user.yaml")
    written = KioskUserConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Usuari de quiosc planificat" if dry_run else "Usuari de quiosc configurat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_thin_client_launcher(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_thin_client_launcher_plan(workspace.rootfs_dir, root / "config/thin-client-launcher.yaml")
    written = ThinClientLauncherConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Llançament de XAAC Thin Client planificat" if dry_run else "Llançament de XAAC Thin Client configurat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_session_supervisor(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_session_supervisor_plan(workspace.rootfs_dir, root / "config/session-supervisor.yaml")
    written = SessionSupervisorConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Supervisió de sessió planificada" if dry_run else "Supervisió de sessió configurada",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_display_layout(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_display_layout_plan(workspace.rootfs_dir, root / "config/display-layout.yaml")
    written = DisplayLayoutConfigurator().execute(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "Disposició de pantalles planificada" if dry_run else "Disposició de pantalles configurada", "executed": not dry_run, "files": [str(path) for path in written], "plan": plan.to_manifest()}, as_json=as_json)
    return 0

def _validate_graphical_session(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_graphical_session_validation_plan(workspace.rootfs_dir, root / "config/graphical-session-validation.yaml")
    written = GraphicalSessionValidationConfigurator().execute(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "Validació de sessió gràfica planificada" if dry_run else "Validació de sessió gràfica configurada", "executed": not dry_run, "files": [str(path) for path in written], "plan": plan.to_manifest()}, as_json=as_json)
    return 0

def _configure_kiosk_restrictions(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_kiosk_restriction_plan(workspace.rootfs_dir, root / "config/kiosk-restrictions.yaml")
    written = KioskRestrictionConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Model de restriccions planificat" if dry_run else "Model de restriccions configurat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_shortcut_lockdown(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_shortcut_lockdown_plan(workspace.rootfs_dir, root / "config/shortcut-lockdown.yaml")
    written = ShortcutLockdownConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Bloqueig de dreceres planificat" if dry_run else "Dreceres de quiosc bloquejades",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_terminal_lockdown(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_terminal_lockdown_plan(workspace.rootfs_dir, root / "config/terminal-lockdown.yaml")
    written = TerminalLockdownConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Bloqueig de terminals planificat" if dry_run else "Terminals i llançadors del quiosc bloquejats",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_tty_control(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_tty_control_plan(workspace.rootfs_dir, root / "config/tty-control.yaml")
    written = TtyControlConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Control dels TTY planificat" if dry_run else "TTY d'usuari bloquejats i TTY administratiu configurat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_kiosk_filesystem(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_kiosk_filesystem_plan(workspace.rootfs_dir, root / "config/kiosk-filesystem.yaml")
    written = KioskFilesystemConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Sistema de fitxers del quiosc planificat" if dry_run else "Sistema de fitxers efímer del quiosc configurat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0


def _configure_local_device_control(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_local_device_control_plan(workspace.rootfs_dir, root / "config/local-device-control.yaml")
    written = LocalDeviceControlConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Control de dispositius locals planificat" if dry_run else "Dispositius locals del quiosc controlats",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0

def _configure_power_action_control(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_power_action_control_plan(workspace.rootfs_dir, root / "config/power-action-control.yaml")
    written = PowerActionControlConfigurator().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Control d'energia planificat" if dry_run else "Apagada i reinici del quiosc controlats",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0


def _install_xaac_thin_client(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_xaac_thin_client_package_plan(
        workspace.rootfs_dir, root, root / "config/xaac-thin-client-package.yaml"
    )
    written = XaacThinClientPackageInstaller().execute(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": "Paquet XAAC Thin Client validat i planificat" if dry_run else "Paquet XAAC Thin Client instal·lat",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }, as_json=as_json)
    return 0


def _install_xaac_agent(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_xaac_agent_plan(
        root / ".build/rootfs", root, root / "config/xaac-agent-package.yaml"
    )
    written = XaacAgentInstaller().execute(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "installed", "manifest": plan.manifest(), "written": [str(path) for path in written]}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else f"XAAC Agent: {payload['status']} ({plan.metadata.version})")
    return 0


def _configure_security_policy(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_security_policy_plan(root / ".build/rootfs", root / "config/security-policy.yaml")
    paths = SecurityPolicyInstaller().install(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Política de seguretat planificada" if dry_run else "Política base de seguretat instal·lada",
        "executed": not dry_run,
        **plan.to_manifest(),
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0


def _configure_account_permissions(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_account_permissions_plan(root / ".build/rootfs", root / "config/account-permissions.yaml")
    paths = AccountPermissionsInstaller().install(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Política d'usuaris i permisos planificada" if dry_run else "Política d'usuaris i permisos instal·lada",
        "executed": not dry_run,
        **plan.manifest(),
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0


def _configure_systemd_hardening(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_systemd_hardening_plan(root / ".build/rootfs", root / "config/systemd-hardening.yaml")
    paths = SystemdHardeningInstaller().install(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Hardening systemd planificat" if dry_run else "Hardening systemd instal·lat",
        "executed": not dry_run,
        **plan.manifest(),
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0


def _configure_apparmor(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_apparmor_plan(root / ".build/rootfs", root / "config/apparmor.yaml")
    paths = AppArmorInstaller().install(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Perfils AppArmor planificats" if dry_run else "Perfils AppArmor instal·lats",
        "executed": not dry_run,
        **plan.manifest(),
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0


def _configure_kernel_hardening(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_kernel_hardening_plan(root / ".build/rootfs", root / "config/kernel-hardening.yaml")
    paths = KernelHardeningInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Hardening del kernel planificat" if dry_run else "Hardening del kernel instal·lat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_file_integrity(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_file_integrity_plan(root / ".build/rootfs", root / "config/file-integrity.yaml")
    paths = FileIntegrityManager().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Integritat de fitxers planificada" if dry_run else "Baseline d’integritat instal·lada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _verify_file_integrity(root: Path, *, repair: bool, as_json: bool) -> int:
    plan = create_file_integrity_plan(root / ".build/rootfs", root / "config/file-integrity.yaml")
    result = FileIntegrityManager().verify(plan, repair=repair)
    _emit({"message": "Integritat correcta" if result["status"] == "ok" else ("Fitxers reparats" if repair else "Canvis d’integritat detectats"), **result}, as_json=as_json)
    return 0 if result["status"] in {"ok", "repaired"} else 4


def _configure_package_signing(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_package_signing_plan(root / ".build/rootfs", root / "config/package-signing.yaml")
    paths = PackageSigningInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Signatura de paquets planificada" if dry_run else "Política de signatura de paquets instal·lada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_secure_boot_tpm(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_secure_boot_tpm_plan(root / ".build/rootfs", root / "config/secure-boot-tpm.yaml")
    paths = SecureBootTpmInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Secure Boot i TPM planificats" if dry_run else "Política Secure Boot i TPM instal·lada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_update_model(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_update_model_plan(root / ".build/rootfs", root / "config/update-model.yaml")
    paths = UpdateModelInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Model d’actualitzacions planificat" if dry_run else "Model d’actualitzacions instal·lat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _create_update_manifest(
    root: Path,
    *,
    target_os_version: str | None,
    channel: str | None,
    minimum_installed_os_version: str | None,
    output: str,
    as_json: bool,
) -> int:
    target = target_os_version or (root / "VERSION").read_text(encoding="utf-8").strip()
    selected_channel = channel
    if selected_channel is None:
        policy = load_update_model(root / "config/update-model.yaml")
        build_channel = load_project_configuration(root).build.channel.value
        selected_channel = resolve_update_channel(policy, build_channel)
    output_path = Path(output)
    if output_path.is_absolute() or ".." in output_path.parts:
        raise UpdateReleaseManifestError("La ruta d'eixida del manifest ha de quedar dins del projecte")
    destination = root / output_path
    manifest = build_release_manifest(
        root,
        root / "config/update-model.yaml",
        target_os_version=target,
        channel=selected_channel,
        minimum_installed_os_version=minimum_installed_os_version,
    )
    write_release_manifest(destination, manifest)
    payload = {
        "status": "ok",
        "message": "Manifest d'actualització generat; resta pendent la signatura OpenPGP externa",
        "phase": "10.1",
        "target_os_version": target,
        "channel": selected_channel,
        "output": str(destination),
        "manifest_sha256": manifest["integrity"]["manifest_payload"],
    }
    _emit(payload, as_json=as_json)
    return 0


def _configure_recovery_model(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_recovery_model_plan(root / ".build/rootfs", root / "config/recovery-model.yaml")
    paths = RecoveryModelInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Model de recuperació planificat" if dry_run else "Model de recuperació instal·lat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_application_recovery(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_application_recovery_plan(root / ".build/rootfs", root / "config/application-recovery.yaml")
    paths = ApplicationRecoveryInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Recuperació d’aplicació planificada" if dry_run else "Recuperació d’aplicació instal·lada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_package_repair(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_package_repair_plan(root / ".build/rootfs", root / "config/package-repair.yaml")
    paths = PackageRepairInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Reparació de paquets planificada" if dry_run else "Reparació de paquets configurada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_local_recovery(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_local_recovery_plan(root / ".build/rootfs", root / "config/local-recovery.yaml")
    paths = LocalRecoveryInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Mode de recuperació local planificat" if dry_run else "Mode de recuperació local configurat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_recovery_partition(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_recovery_partition_plan(root / ".build/rootfs", root / "config/recovery-partition.yaml")
    paths = RecoveryPartitionInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Partició de recuperació planificada" if dry_run else "Partició de recuperació configurada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_factory_reset(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_factory_reset_plan(root / ".build/rootfs", root / "config/factory-reset.yaml")
    paths = FactoryResetInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Factory reset planificat" if dry_run else "Factory reset configurat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_usb_recovery(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_usb_recovery_plan(root / ".build/rootfs", root / "config/usb-recovery.yaml")
    paths = UsbRecoveryInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Recuperació USB planificada" if dry_run else "Recuperació USB configurada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_pxe_recovery(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_pxe_recovery_plan(root / ".build/rootfs", root / "config/pxe-recovery.yaml")
    paths = PxeRecoveryInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Recuperació PXE planificada" if dry_run else "Recuperació PXE configurada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_iso(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_iso_build_plan(root, root / "config/iso-builder.yaml")
    paths = IsoBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Constructor ISO planificat" if dry_run else "Constructor ISO preparat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_img(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_img_build_plan(root, root / "config/img-builder.yaml")
    paths = ImgBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Constructor IMG planificat" if dry_run else "Constructor IMG preparat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_pxe(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_pxe_build_plan(root, root / "config/pxe-builder.yaml")
    paths = PxeBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Paquet PXE planificat" if dry_run else "Paquet PXE preparat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_installer(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_installer_build_plan(root, root / "config/installer-builder.yaml")
    paths = InstallerBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Instal·lador planificat" if dry_run else "Instal·lador preparat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_cloning(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_mass_cloning_plan(root, root / "config/mass-cloning.yaml")
    paths = MassCloningBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Clonació massiva planificada" if dry_run else "Clonació massiva preparada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_image_tests(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_image_test_suite_plan(root, root / 'config/image-tests.yaml')
    paths = ImageTestSuiteBuilder().prepare(plan, dry_run=dry_run)
    payload = {'status': 'planned' if dry_run else 'ok', 'message': 'Proves d’imatge planificades' if dry_run else 'Proves d’imatge preparades', 'executed': not dry_run, **plan.manifest(), 'files': [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_hardware_tests(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_hardware_final_tests_plan(root, root / 'config/hardware-final-tests.yaml')
    paths = HardwareFinalTestsBuilder().prepare(plan, dry_run=dry_run)
    payload = {'status': 'planned' if dry_run else 'ok', 'message': 'Proves finals de maquinari planificades' if dry_run else 'Proves finals de maquinari preparades', 'executed': not dry_run, **plan.manifest(), 'files': [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0

def _build_performance_tests(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_performance_stability_plan(root, root / 'config/performance-stability.yaml')
    paths = PerformanceStabilityBuilder().prepare(plan, dry_run=dry_run)
    payload = {'status': 'planned' if dry_run else 'ok', 'message': 'Proves de rendiment planificades' if dry_run else 'Proves de rendiment preparades', 'executed': not dry_run, **plan.manifest(), 'files': [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_documentation(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_documentation_plan(root, root / 'config/documentation.yaml')
    paths = DocumentationBuilder().prepare(plan, dry_run=dry_run)
    payload = {'status': 'planned' if dry_run else 'ok', 'message': 'Documentació planificada' if dry_run else 'Documentació preparada', 'executed': not dry_run, **plan.manifest(), 'files': [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_production_packaging(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_production_packaging_plan(root, root / "config/production-packaging.yaml")
    paths = ProductionPackagingBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Packaging de producció planificat" if dry_run else "Packaging de producció preparat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_release_candidate(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_release_candidate_plan(root, root / "config/release-candidate.yaml")
    paths = ReleaseCandidateBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Release candidate planificada" if dry_run else "Release candidate congelada i preparada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _build_final_release(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_final_release_plan(root, root / "config/final-release.yaml")
    paths = FinalReleaseBuilder().prepare(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Release final planificada" if dry_run else "Release estable 1.0.0 preparada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_xaac_apt_repository(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_xaac_apt_repository_plan(root / ".build/rootfs", root / "config/xaac-apt-repository.yaml")
    paths = XaacAptRepositoryInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Repositori APT XAAC planificat" if dry_run else "Repositori APT XAAC configurat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_update_service(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_update_service_plan(root / ".build/rootfs", root / "config/update-service.yaml")
    paths = UpdateServiceInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Servei d’actualitzacions planificat" if dry_run else "Servei d’actualitzacions configurat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_update_verification(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_update_verification_plan(root / ".build/rootfs", root / "config/update-verification.yaml")
    paths = UpdateVerificationInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Verificació d’actualitzacions planificada" if dry_run else "Verificació d’actualitzacions configurada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_transactional_update(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_transactional_update_plan(root / ".build/rootfs", root / "config/transactional-update.yaml")
    paths = TransactionalUpdateInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Instal·lació transaccional planificada" if dry_run else "Instal·lació transaccional configurada", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_package_rollback(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_package_rollback_plan(root / ".build/rootfs", root / "config/package-rollback.yaml")
    paths = PackageRollbackInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "ok", "message": "Rollback de paquets configurat", "dry_run": dry_run, "outputs": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0

def _configure_update_rings(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_update_rings_plan(root / ".build/rootfs", root / "config/update-rings.yaml")
    paths = UpdateRingsInstaller().install(plan, dry_run=dry_run)
    payload = {"status": "planned" if dry_run else "ok", "message": "Desplegament per anells planificat" if dry_run else "Desplegament per anells configurat", "executed": not dry_run, **plan.manifest(), "files": [str(path) for path in paths]}
    _emit(payload, as_json=as_json)
    return 0


def _configure_update_sources(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = create_update_sources_plan(root / ".build/rootfs", root / "config/update-sources.yaml")
    paths = UpdateSourcesInstaller().install(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Fonts d’actualització planificades" if dry_run else "Fonts d’actualització configurades",
        "executed": not dry_run,
        **plan.manifest(),
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0


def _configure_device_identity(root: Path, *, dry_run: bool, as_json: bool) -> int:
    identity = DeviceIdentityManager().create(
        root / ".build/rootfs", root / "config/device-identity.yaml", dry_run=dry_run
    )
    payload = {"status": "planned" if dry_run else "ok", "identity": identity.to_dict()}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else f"Identitat del dispositiu: {identity.uuid} ({identity.hostname})")
    return 0


def _configure_first_boot(root: Path, *, dry_run: bool, as_json: bool) -> int:
    paths = FirstBootInstaller().install(
        root / ".build/rootfs", root / "config/first-boot.yaml", dry_run=dry_run
    )
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Servei de primer inici planificat" if dry_run else "Servei de primer inici configurat",
        "executed": not dry_run,
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0

def _configure_local_integration(root: Path, *, dry_run: bool, as_json: bool) -> int:
    plan = LocalIntegrationConfigurator().install(
        root / ".build/rootfs", root / "config/local-integration.yaml", dry_run=dry_run
    )
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Contracte local planificat" if dry_run else "Contracte local OS-Agent configurat",
        "executed": not dry_run,
        "files": [str(path) for path in plan.files],
    }
    _emit(payload, as_json=as_json)
    return 0

def _configure_policy_application(root: Path, *, dry_run: bool, as_json: bool) -> int:
    paths = PolicyApplicationManager(root / ".build/rootfs", root / "config/policy-application.yaml").install(dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Aplicació de polítiques planificada" if dry_run else "Aplicació transaccional de polítiques configurada",
        "executed": not dry_run,
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0

def _collect_device_inventory(root: Path, *, dry_run: bool, as_json: bool) -> int:
    collector = DeviceInventoryCollector(root / ".build/rootfs", root / "config/device-inventory.yaml")
    paths = collector.install(dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Inventari del dispositiu planificat" if dry_run else "Inventari del dispositiu recollit",
        "executed": not dry_run,
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0

def _configure_xms_enrollment(root: Path, *, dry_run: bool, as_json: bool) -> int:
    manager = XmsEnrollmentManager(root / ".build/rootfs", root / "config/xms-enrollment.yaml")
    paths = manager.install(dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Enrolament XMS planificat" if dry_run else "Enrolament XMS configurat",
        "executed": not dry_run,
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0


def _configure_ip_addressing(root: Path, *, source: str, mode: str, address: str | None, gateway: str | None, dns: tuple[str, ...], rollback: bool, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    request = IpAddressingRequest(source=source, mode=mode, address=address, gateway=gateway, dns=dns)
    plan = create_ip_addressing_plan(workspace.rootfs_dir, root / "config/ip-addressing.yaml", request)
    manager = IpAddressingManager()
    paths = manager.rollback(plan, dry_run=dry_run) if rollback else manager.apply(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": ("Rollback IP planificat" if dry_run else "Configuració IP restaurada") if rollback else ("Configuració IP planificada" if dry_run else "Configuració IP aplicada"),
        "executed": not dry_run,
        "source": source,
        "mode": mode,
        "rollback": rollback,
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0



def _configure_network_services(root: Path, *, source: str, dns: tuple[str, ...], domains: tuple[str, ...], ntp: tuple[str, ...], proxy: str | None, no_proxy: tuple[str, ...], rollback: bool, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    request = NetworkServicesRequest(source=source, dns=dns, domains=domains, ntp=ntp, proxy=proxy, no_proxy=no_proxy)
    plan = create_network_services_plan(workspace.rootfs_dir, root / "config/network-services.yaml", request)
    manager = NetworkServicesManager()
    paths = manager.rollback(plan, dry_run=dry_run) if rollback else manager.apply(plan, dry_run=dry_run)
    _emit({
        "status": "planned" if dry_run else "ok",
        "message": ("Rollback de serveis planificat" if dry_run else "Serveis de xarxa restaurats") if rollback else ("Serveis de xarxa planificats" if dry_run else "DNS, NTP i proxy configurats"),
        "executed": not dry_run,
        "source": source,
        "rollback": rollback,
        "files": [str(path) for path in paths],
    }, as_json=as_json)
    return 0

def _configure_vlan(root: Path, *, source: str, vlan_id: int, name: str | None, parent: str, mode: str, address: str | None, gateway: str | None, dns: tuple[str, ...], rollback: bool, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_vlan_plan(workspace.rootfs_dir, root / "config/vlan.yaml", VlanRequest(source=source, vlan_id=vlan_id, name=name, parent=parent, mode=mode, address=address, gateway=gateway, dns=dns))
    manager = VlanManager()
    paths = manager.rollback(plan, dry_run=dry_run) if rollback else manager.apply(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "VLAN restaurada" if rollback else "VLAN configurada", "executed": not dry_run, "vlan_id": vlan_id, "source": source, "rollback": rollback, "files": [str(path) for path in paths]}, as_json=as_json)
    return 0

def _configure_ieee8021x(root: Path, *, source: str, interface: str, eap: str, identity: str, anonymous_identity: str | None, ca_certificate: str, client_certificate: str | None, private_key: str | None, private_key_password: str | None, password: str | None, rollback: bool, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    request = Ieee8021xRequest(source=source, interface=interface, eap=eap, identity=identity, anonymous_identity=anonymous_identity, ca_certificate=ca_certificate, client_certificate=client_certificate, private_key=private_key, private_key_password=private_key_password, password=password)
    plan = create_ieee8021x_plan(workspace.rootfs_dir, root / "config/ieee8021x.yaml", request)
    manager = Ieee8021xManager()
    paths = manager.rollback(plan, dry_run=dry_run) if rollback else manager.apply(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "IEEE 802.1X restaurat" if rollback else "IEEE 802.1X configurat", "executed": not dry_run, "eap": eap, "source": source, "rollback": rollback, "files": [str(path) for path in paths]}, as_json=as_json)
    return 0

def _configure_local_admin(root: Path, *, source: str, username: str, password_hash: str | None, force_password_change: bool, rollback: bool, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_local_admin_plan(workspace.rootfs_dir, root / "config/local-admin.yaml", LocalAdminRequest(source=source, username=username, password_hash=password_hash, force_password_change=force_password_change))
    manager = LocalAdminManager()
    paths = manager.rollback(plan, dry_run=dry_run) if rollback else manager.apply(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "Perfil administrador restaurat" if rollback else "Perfil administrador configurat", "executed": not dry_run, "source": source, "username": username, "rollback": rollback, "files": [str(path) for path in paths]}, as_json=as_json)
    return 0

def _configure_network_manager(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_network_manager_plan(workspace.rootfs_dir, root / "config/network-manager.yaml")
    paths = NetworkManagerConfigurator().install(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Gestor de xarxa planificat" if dry_run else "Gestor de xarxa configurat",
        "executed": not dry_run,
        "backend": "systemd-networkd",
        "files": [str(path) for path in paths],
    }
    _emit(payload, as_json=as_json)
    return 0


def _inspect_ethernet(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    profile = load_ethernet_profile(root / "config/ethernet.yaml")
    report = compare_ethernet(EthernetDetector().detect(), profile)
    if report_path is not None:
        destination = report_path if report_path.is_absolute() else root / report_path
        write_ethernet_report(report, destination)
    payload = {"status": "ok" if report.compatible else "incompatible", "message": "Ethernet compatible" if report.compatible else "Ethernet no compleix el perfil Wyse 3040", **report.to_dict()}
    if as_json:
        _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4


def _configure_ethernet(root: Path, *, dry_run: bool, mode: str | None, address: str | None, gateway: str | None, dns: tuple[str, ...], as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_ethernet_configuration_plan(workspace.rootfs_dir, root / "config/ethernet.yaml", mode=mode, address=address, gateway=gateway, dns=dns)
    written = EthernetConfigurator().execute(plan, dry_run=dry_run)
    payload = {
        "status": "planned" if dry_run else "ok",
        "message": "Configuració Ethernet planificada" if dry_run else "Ethernet configurada",
        "executed": not dry_run,
        "files": [str(path) for path in written],
        "plan": plan.to_manifest(),
    }
    _emit(payload, as_json=as_json)
    return 0

def _inspect_audio(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    profile = load_audio_profile(root / "config/audio.yaml")
    report = compare_audio(AudioDetector().detect(), profile)
    if report_path is not None:
        destination = report_path if report_path.is_absolute() else root / report_path
        write_audio_report(report, destination)
    payload = {"status": "ok" if report.compatible else "incompatible", "message": "Àudio compatible" if report.compatible else "L'àudio no compleix el perfil Wyse 3040", **report.to_dict()}
    if as_json:
        _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4


def _configure_audio(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_audio_configuration_plan(workspace.rootfs_dir, root / "config/audio.yaml")
    written = AudioConfigurator().execute(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "Configuració d'àudio planificada" if dry_run else "Àudio configurat", "executed": not dry_run, "files": [str(path) for path in written], "plan": plan.to_manifest()}, as_json=as_json)
    return 0


def _inspect_usb(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    profile = load_usb_profile(root / "config/usb.yaml")
    report = compare_usb(UsbDetector().detect(), profile)
    if report_path is not None:
        destination = report_path if report_path.is_absolute() else root / report_path
        write_usb_report(report, destination)
    payload = {"status": "ok" if report.compatible else "incompatible", "message": "USB i perifèrics compatibles" if report.compatible else "USB o perifèrics no compleixen el perfil Wyse 3040", **report.to_dict()}
    if as_json:
        _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4


def _configure_usb(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_usb_configuration_plan(workspace.rootfs_dir, root / "config/usb.yaml")
    written = UsbConfigurator().execute(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "Configuració USB planificada" if dry_run else "USB i perifèrics configurats", "executed": not dry_run, "files": [str(path) for path in written], "plan": plan.to_manifest()}, as_json=as_json)
    return 0


def _inspect_power(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    report = compare_power(PowerDetector().detect(), load_power_profile(root / "config/power.yaml"))
    if report_path is not None:
        write_power_report(report, report_path if report_path.is_absolute() else root / report_path)
    payload={"status":"ok" if report.compatible else "incompatible","message":"Energia i temperatura compatibles" if report.compatible else "El perfil energètic o tèrmic no és compatible",**report.to_dict()}
    if as_json: _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks: print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4

def _configure_power(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace=WorkspaceManager(root).load_existing();plan=create_power_configuration_plan(workspace.rootfs_dir,root / "config/power.yaml");written=PowerConfigurator().execute(plan,dry_run=dry_run)
    _emit({"status":"planned" if dry_run else "ok","message":"Configuració energètica planificada" if dry_run else "Energia i temperatura configurades","executed":not dry_run,"files":[str(p) for p in written],"plan":plan.to_manifest()},as_json=as_json);return 0

def _inspect_resources(root: Path, *, report_path: Path | None, as_json: bool) -> int:
    report = compare_resources(ResourceDetector().detect(), load_resource_profile(root / "config/resources.yaml"))
    if report_path is not None:
        write_resource_report(report, report_path if report_path.is_absolute() else root / report_path)
    payload = {"status": "ok" if report.compatible else "incompatible", "message": "Recursos compatibles" if report.compatible else "La memòria o el disc no compleixen el perfil Wyse 3040", **report.to_dict()}
    if as_json:
        _emit(payload, as_json=True)
    else:
        print(payload["message"])
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.actual} (esperat: {check.expected})")
    return 0 if report.compatible else 4

def _configure_resources(root: Path, *, dry_run: bool, as_json: bool) -> int:
    workspace = WorkspaceManager(root).load_existing()
    plan = create_resource_configuration_plan(workspace.rootfs_dir, root / "config/resources.yaml")
    written = ResourceConfigurator().execute(plan, dry_run=dry_run)
    _emit({"status": "planned" if dry_run else "ok", "message": "Optimització de recursos planificada" if dry_run else "RAM i disc optimitzats", "executed": not dry_run, "files": [str(p) for p in written], "plan": plan.to_manifest()}, as_json=as_json)
    return 0

def _clean(root: Path, *, force: bool, as_json: bool) -> int:
    if not force:
        _emit(
            {
                "status": "confirmation_required",
                "message": "Useu clean --force per eliminar .build",
            },
            as_json=as_json,
        )
        return 3
    removed = WorkspaceManager(root).clean()
    message = "Directori .build eliminat" if removed else "No hi ha artefactes .build"
    _emit({"status": "ok", "message": message}, as_json=as_json)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        ensure_supported_python()
    except UnsupportedPythonError as exc:
        parser.exit(2, f"error: {exc}\n")

    root = args.root.resolve()
    try:
        if args.command == "version":
            _emit(
                {
                    "status": "ok",
                    "message": f"{PROJECT_NAME} {__version__}",
                    "version": __version__,
                },
                as_json=args.json,
            )
            return 0
        if args.command == "check-python":
            _emit({"status": "ok", "message": "Python 3.13 compatible"}, as_json=args.json)
            return 0
        if args.command == "validate":
            return _validate(root, as_json=args.json)
        if args.command == "inspect":
            return _inspect(root, as_json=args.json)
        if args.command == "inspect-hardware":
            return _inspect_hardware(root, report_path=args.report, as_json=args.json)
        if args.command == "inspect-emmc":
            return _inspect_emmc(root, report_path=args.report, as_json=args.json)
        if args.command == "configure-emmc":
            return _configure_emmc(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "inspect-graphics":
            return _inspect_graphics(root, report_path=args.report, as_json=args.json)
        if args.command == "configure-graphics":
            return _configure_graphics(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-graphical-stack":
            return _configure_graphical_stack(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-compositor":
            return _configure_compositor(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-session-manager":
            return _configure_session_manager(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-kiosk-user":
            return _configure_kiosk_user(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-thin-client-launcher":
            return _configure_thin_client_launcher(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-session-supervisor":
            return _configure_session_supervisor(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-display-layout":
            return _configure_display_layout(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "validate-graphical-session":
            return _validate_graphical_session(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-kiosk-restrictions":
            return _configure_kiosk_restrictions(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-shortcut-lockdown":
            return _configure_shortcut_lockdown(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-terminal-lockdown":
            return _configure_terminal_lockdown(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-tty-control":
            return _configure_tty_control(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-kiosk-filesystem":
            return _configure_kiosk_filesystem(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-local-device-control":
            return _configure_local_device_control(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-power-action-control":
            return _configure_power_action_control(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "install-xaac-thin-client":
            return _install_xaac_thin_client(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "install-xaac-agent":
            return _install_xaac_agent(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-security-policy":
            return _configure_security_policy(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-account-permissions":
            return _configure_account_permissions(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-systemd-hardening":
            return _configure_systemd_hardening(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-apparmor":
            return _configure_apparmor(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-kernel-hardening":
            return _configure_kernel_hardening(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-file-integrity":
            return _configure_file_integrity(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "verify-file-integrity":
            return _verify_file_integrity(root, repair=args.repair, as_json=args.json)
        if args.command == "configure-package-signing":
            return _configure_package_signing(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-secure-boot-tpm":
            return _configure_secure_boot_tpm(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-update-model":
            return _configure_update_model(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "create-update-manifest":
            return _create_update_manifest(
                root,
                target_os_version=args.target_os_version,
                channel=args.channel,
                minimum_installed_os_version=args.minimum_installed_os_version,
                output=args.output,
                as_json=args.json,
            )
        if args.command == "configure-recovery-model":
            return _configure_recovery_model(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-application-recovery":
            return _configure_application_recovery(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-package-repair":
            return _configure_package_repair(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-local-recovery":
            return _configure_local_recovery(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-recovery-partition":
            return _configure_recovery_partition(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-factory-reset":
            return _configure_factory_reset(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-usb-recovery":
            return _configure_usb_recovery(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-pxe-recovery":
            return _configure_pxe_recovery(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-iso":
            return _build_iso(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-img":
            return _build_img(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-pxe":
            return _build_pxe(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-installer":
            return _build_installer(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-cloning":
            return _build_cloning(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-image-tests":
            return _build_image_tests(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-hardware-tests":
            return _build_hardware_tests(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-performance-tests":
            return _build_performance_tests(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-documentation":
            return _build_documentation(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-production-packaging":
            return _build_production_packaging(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-release-candidate":
            return _build_release_candidate(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-final-release":
            return _build_final_release(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-xaac-apt-repository":
            return _configure_xaac_apt_repository(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-update-service":
            return _configure_update_service(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-update-verification":
            return _configure_update_verification(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-transactional-update":
            return _configure_transactional_update(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-package-rollback":
            return _configure_package_rollback(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-update-rings":
            return _configure_update_rings(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-update-sources":
            return _configure_update_sources(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-device-identity":
            return _configure_device_identity(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-first-boot":
            return _configure_first_boot(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-local-integration":
            return _configure_local_integration(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-policy-application":
            return _configure_policy_application(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "collect-device-inventory":
            return _collect_device_inventory(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-xms-enrollment":
            return _configure_xms_enrollment(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-network-manager":
            return _configure_network_manager(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-ip-addressing":
            return _configure_ip_addressing(root, source=args.source, mode=args.mode, address=args.address, gateway=args.gateway, dns=tuple(args.dns), rollback=args.rollback, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-network-services":
            return _configure_network_services(root, source=args.source, dns=tuple(args.dns), domains=tuple(args.domain), ntp=tuple(args.ntp), proxy=args.proxy, no_proxy=tuple(args.no_proxy), rollback=args.rollback, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-vlan":
            return _configure_vlan(root, source=args.source, vlan_id=args.vlan_id, name=args.name, parent=args.parent, mode=args.mode, address=args.address, gateway=args.gateway, dns=tuple(args.dns), rollback=args.rollback, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-ieee8021x":
            return _configure_ieee8021x(root, source=args.source, interface=args.interface, eap=args.eap, identity=args.identity, anonymous_identity=args.anonymous_identity, ca_certificate=args.ca_certificate, client_certificate=args.client_certificate, private_key=args.private_key, private_key_password=args.private_key_password, password=args.password, rollback=args.rollback, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-local-admin":
            return _configure_local_admin(root, source=args.source, username=args.username, password_hash=args.password_hash, force_password_change=not args.no_force_password_change, rollback=args.rollback, dry_run=args.dry_run, as_json=args.json)
        if args.command == "inspect-ethernet":
            return _inspect_ethernet(root, report_path=args.report, as_json=args.json)
        if args.command == "configure-ethernet":
            return _configure_ethernet(root, dry_run=args.dry_run, mode=args.mode, address=args.address, gateway=args.gateway, dns=tuple(args.dns), as_json=args.json)
        if args.command == "inspect-audio":
            return _inspect_audio(root, report_path=args.report, as_json=args.json)
        if args.command == "configure-audio":
            return _configure_audio(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "inspect-usb":
            return _inspect_usb(root, report_path=args.report, as_json=args.json)
        if args.command == "configure-usb":
            return _configure_usb(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "inspect-power":
            return _inspect_power(root, report_path=args.report, as_json=args.json)
        if args.command == "configure-power":
            return _configure_power(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "inspect-resources":
            return _inspect_resources(root, report_path=args.report, as_json=args.json)
        if args.command == "configure-resources":
            return _configure_resources(root, dry_run=args.dry_run, as_json=args.json)
        if args.command in {"prepare", "build"}:
            return _prepare(root, as_json=args.json)
        if args.command == "bootstrap":
            return _bootstrap(
                root, dry_run=args.dry_run, keep_partial=args.keep_partial, as_json=args.json
            )
        if args.command == "configure-apt":
            return _configure_apt(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "install-packages":
            return _install_packages(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-kernel":
            return _configure_kernel(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-uefi":
            return _configure_uefi(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-partitions":
            return _configure_partitions(root, device=args.device, dry_run=args.dry_run, confirm_destructive=args.confirm_destructive, as_json=args.json)
        if args.command == "configure-systemd":
            return _configure_systemd(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-localization":
            return _configure_localization(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "build-rootfs":
            return _build_image(root, dry_run=args.dry_run, as_json=args.json, rootfs_only=True)
        if args.command == "build-image":
            return _build_image(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-system":
            return _configure_system(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-users":
            return _configure_users(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-network":
            return _configure_network(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-ssh":
            return _configure_ssh(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "configure-firewall":
            return _configure_firewall(root, dry_run=args.dry_run, as_json=args.json)
        if args.command == "clean":
            return _clean(root, force=args.force, as_json=args.json)
    except (
        AptConfigurationError,
        BootstrapError,
        BootableImageError,
        BuildDependencyError,
        ConfigurationError,
        HookError,
        HardwareInventoryError,
        EmmcSupportError,
        IntelGraphicsError, GraphicalStackError, CompositorError, SessionManagerError, KioskUserError, ThinClientLauncherError, SessionSupervisorError, DisplayLayoutError, GraphicalSessionValidationError, KioskRestrictionError, ShortcutLockdownError, TerminalLockdownError, TtyControlError, KioskFilesystemError, LocalDeviceControlError, PowerActionControlError, XaacThinClientPackageError, XaacAgentPackageError, SecurityPolicyError, AccountPermissionsError, SystemdHardeningError, AppArmorError, KernelHardeningError, FileIntegrityError, PackageSigningError, SecureBootTpmError, UpdateModelError, UpdateReleaseManifestError, RecoveryModelError, ApplicationRecoveryError, PackageRepairError, LocalRecoveryError, RecoveryPartitionError, FactoryResetError, UsbRecoveryError, PxeRecoveryError, IsoBuilderError, ImgBuilderError, PxeBuilderError, InstallerBuilderError, MassCloningError, ImageTestSuiteError, HardwareFinalTestsError, PerformanceStabilityError, DocumentationError, ProductionPackagingError, ReleaseCandidateError, FinalReleaseError, XaacAptRepositoryError, UpdateServiceError, UpdateVerificationError, TransactionalUpdateError, PackageRollbackError, UpdateRingsError, UpdateSourcesError, DeviceIdentityError, FirstBootError, LocalIntegrationError, PolicyApplicationError, DeviceInventoryError, XmsEnrollmentError, NetworkManagerError, IpAddressingError, NetworkServicesError, VlanConfigurationError, Ieee8021xError, LocalAdminError, EthernetSupportError, AudioSupportError, UsbPeripheralError, PowerThermalError, ResourceOptimizationError,
        KernelInitramfsError,
        LocalizationError,
        FirewallConfigurationError,
        NetworkConfigurationError,
        PackageInstallationError,
        PartitioningError,
        SshConfigurationError,
        SystemConfigurationError,
        SystemdConfigurationError,
        UefiBootError,
        UserConfigurationError,
        TemplateError,
        WorkspaceError,
        WorkspaceLockedError,
        OSError,
        ValueError,
    ) as exc:
        if args.json:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
            return 2
        parser.exit(2, f"error: {exc}\n")

    parser.print_help()
    return 0
