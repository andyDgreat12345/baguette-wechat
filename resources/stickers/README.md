# 自带表情 / Bring your own stickers

The development account used a private 36-sticker guide, with WeChat Favorites in reverse guide order. The guide PDF, meme images and personal meanings are not redistributed because ownership was not verified. Import only assets you may use.

The current sender expects IDs S01–S36, five columns, a calibrated 1280×800 dark layout and per-image `wechat_verified: true`. A position is not a meaning: store a description, emotion, appropriate situations, avoid-situations and confidence alongside the asset. When a user corrects a meaning, bind the correction to the actual image hash in the original memory system.

For a reverse collection of N images, `wechat_position = N + 1 - guide_number`; zero-based row/column derive from the Favorites column count. The implementation currently validates the 36-item layout; another size requires adapting the configured sender and regression tests.

Never set verification flags by guess. Capture top and bottom rows, match each thumbnail and test a single agreed sticker in a private test chat. Incoming recognition uses the original QQ classifier and may be wrong; animated stickers provide only the visible frame.

See `catalog.example.json` and the installation calibration section.
