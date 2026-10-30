import 'package:material_ui/material_ui.dart';

/// Lets the bar of a root page open the home drawer and take its solid fill.
///
/// Each page builds its own scaffold below the home shell, so `Scaffold.of`
/// from a page finds the page's scaffold, not the one holding the drawer.
class DrawerScope extends InheritedWidget {
  const DrawerScope({super.key, required this.open, required super.child});

  final VoidCallback? open;

  static VoidCallback? openerOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<DrawerScope>()?.open;

  @override
  bool updateShouldNotify(DrawerScope oldWidget) => open != oldWidget.open;
}
