import flet as ft


def update_controls(controls: list[ft.Control]) -> None:
    for control in controls:
        control.update()
