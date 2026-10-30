import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter_test/flutter_test.dart';

String _androidAttribute(String source, String element, String attribute) {
  final elementTag = RegExp('<$element\\b[^>]*>').firstMatch(source)!.group(0)!;
  return RegExp(
    'android:$attribute="([^"]+)"',
  ).firstMatch(elementTag)!.group(1)!;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('TV launcher icons meet density-specific minimum sizes', () async {
    const expectedSizes = {
      'mdpi': 80,
      'hdpi': 120,
      'xhdpi': 160,
      'xxhdpi': 240,
      'xxxhdpi': 320,
    };

    for (final MapEntry(key: density, value: size) in expectedSizes.entries) {
      final file = File(
        'android/app/src/main/res/'
        'mipmap-television-$density/ic_launcher.webp',
      );
      expect(file.existsSync(), isTrue, reason: 'missing ${file.path}');

      final codec = await ui.instantiateImageCodec(await file.readAsBytes());
      final frame = await codec.getNextFrame();
      expect(
        (frame.image.width, frame.image.height),
        (size, size),
        reason: file.path,
      );
      frame.image.dispose();
      codec.dispose();
    }
  });

  test('TV adaptive launcher icon stays centered in the safe zone', () async {
    final adaptiveIcon = File(
      'android/app/src/main/res/'
      'mipmap-television-anydpi-v26/ic_launcher.xml',
    ).readAsStringSync();
    expect(
      _androidAttribute(adaptiveIcon, 'foreground', 'drawable'),
      '@drawable/ic_launcher_foreground_tv',
    );
    expect(
      _androidAttribute(adaptiveIcon, 'background', 'drawable'),
      '@color/ic_launcher_background',
    );

    final file = File(
      'android/app/src/main/res/drawable-xxxhdpi/'
      'ic_launcher_foreground_tv.png',
    );
    final codec = await ui.instantiateImageCodec(await file.readAsBytes());
    final image = (await codec.getNextFrame()).image;
    final pixels = (await image.toByteData())!;
    final size = image.width;
    var (left, top, right, bottom) = (size, size, 0, 0);
    for (var y = 0; y < size; y++) {
      for (var x = 0; x < size; x++) {
        if (pixels.getUint8((y * size + x) * 4 + 3) > 24) {
          left = left < x ? left : x;
          top = top < y ? top : y;
          right = right > x + 1 ? right : x + 1;
          bottom = bottom > y + 1 ? bottom : y + 1;
        }
      }
    }
    image.dispose();
    codec.dispose();

    final dp = 108 / size;
    final transformedBounds = ui.Rect.fromLTRB(
      left * dp,
      top * dp,
      right * dp,
      bottom * dp,
    );
    const safeZone = ui.Rect.fromLTWH(18, 18, 72, 72);

    expect(transformedBounds.left, greaterThanOrEqualTo(safeZone.left));
    expect(transformedBounds.top, greaterThanOrEqualTo(safeZone.top));
    expect(transformedBounds.right, lessThanOrEqualTo(safeZone.right));
    expect(transformedBounds.bottom, lessThanOrEqualTo(safeZone.bottom));
    expect(transformedBounds.center.dx, closeTo(safeZone.center.dx, 0.5));
    expect(transformedBounds.center.dy, closeTo(safeZone.center.dy, 0.5));
  });
}
