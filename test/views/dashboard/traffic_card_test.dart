import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/ui/line_chart.dart';
import 'package:fl_clash/views/dashboard/layout.dart';
import 'package:fl_clash/views/dashboard/widgets/card.dart';
import 'package:fl_clash/views/dashboard/widgets/traffic.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import '../../helpers/test_app.dart';

void main() {
  late ProviderContainer container;

  setUp(() {
    container = ProviderContainer();
    globalState.container = container;
  });

  tearDown(() => container.dispose());

  Future<void> pumpNetworkSpeedCard(WidgetTester tester) async {
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const TestApp(
          locale: Locale('en'),
          child: Scaffold(
            body: Align(
              alignment: Alignment.topLeft,
              child: SizedBox(
                width: 380,
                child: DashboardDensityScope(
                  density: DashboardDensity.mobile,
                  scale: 1,
                  child: NetworkSpeedCard(),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('LineChart skips repaints when appended idle samples match', (
    tester,
  ) async {
    Future<void> pumpChart(List<double> values, int revision) {
      return tester.pumpWidget(
        MaterialApp(
          home: SizedBox(
            width: 200,
            height: 80,
            child: LineChart(
              values: values,
              revision: revision,
              capacity: 4,
              minScale: 1024,
              color: Colors.blue,
              baselineRatio: 1,
            ),
          ),
        ),
      );
    }

    final chartPaintFinder = find.descendant(
      of: find.byType(LineChart),
      matching: find.byType(CustomPaint),
    );

    await pumpChart([0, 0, 0, 0], 1);
    final firstPainter = tester.widget<CustomPaint>(chartPaintFinder).painter!;

    await pumpChart([0, 0, 0, 0], 2);
    final idlePainter = tester.widget<CustomPaint>(chartPaintFinder).painter!;
    expect(idlePainter.shouldRepaint(firstPainter), isFalse);

    await pumpChart([0, 0, 0, 2048], 3);
    final activePainter = tester.widget<CustomPaint>(chartPaintFinder).painter!;
    expect(activePainter.shouldRepaint(idlePainter), isTrue);
  });

  testWidgets(
    'NetworkSpeedCard keeps static chrome across idle traffic ticks',
    (tester) async {
      await pumpNetworkSpeedCard(tester);

      var headerRebuilds = 0;
      final previousHook = debugOnRebuildDirtyWidget;
      debugOnRebuildDirtyWidget = (element, builtOnce) {
        if (element.widget is DashboardCardHeader) {
          headerRebuilds++;
        }
        previousHook?.call(element, builtOnce);
      };
      addTearDown(() => debugOnRebuildDirtyWidget = previousHook);

      container.read(trafficsProvider.notifier).addTraffic(const Traffic());
      await tester.pump();
      container.read(trafficsProvider.notifier).addTraffic(const Traffic());
      await tester.pump();

      expect(headerRebuilds, 0);

      container
          .read(trafficsProvider.notifier)
          .addTraffic(const Traffic(up: 1024, down: 2048));
      container.read(totalTrafficProvider.notifier).value = const Traffic(
        up: 4096,
        down: 8192,
      );
      await tester.pump();

      expect(headerRebuilds, 0);
      expect(find.textContaining('KB/s', findRichText: true), findsNWidgets(2));
    },
  );
}
