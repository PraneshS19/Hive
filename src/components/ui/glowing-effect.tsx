import { useEffect, useRef } from 'react';
import { animate } from 'motion/react';
import './glowing-effect.css';

const boxSelector = [
  ':is(div, article, section):is(.card, .panel, .tile, .box, .tilt-card)',
  ':is(div, article, section)[class*="-card"]',
  ':is(div, article, section)[class*="-panel"]',
  ':is(div, article, section)[class*="-tile"]',
  ':is(div, article, section)[class*="-box"]',
].join(', ');

export function GlowingEffect() {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;

    let activeBox: HTMLElement | null = null;
    let angleAnimation: ReturnType<typeof animate> | null = null;
    let pointer = { x: 0, y: 0 };

    const hide = () => {
      angleAnimation?.stop();
      angleAnimation = null;
      activeBox = null;
      overlay.style.opacity = '0';
    };

    const update = () => {
      if (!activeBox) return;

      const rect = activeBox.getBoundingClientRect();
      const proximity = 64;
      const inRange =
        pointer.x >= rect.left - proximity &&
        pointer.x <= rect.right + proximity &&
        pointer.y >= rect.top - proximity &&
        pointer.y <= rect.bottom + proximity;

      if (!inRange) {
        hide();
        return;
      }

      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const distance = Math.hypot(pointer.x - centerX, pointer.y - centerY);
      const inactiveRadius = Math.min(rect.width, rect.height) * 0.35;

      overlay.style.left = `${rect.left}px`;
      overlay.style.top = `${rect.top}px`;
      overlay.style.width = `${rect.width}px`;
      overlay.style.height = `${rect.height}px`;
      overlay.style.borderRadius = getComputedStyle(activeBox).borderRadius;

      if (distance < inactiveRadius) {
        angleAnimation?.stop();
        angleAnimation = null;
        overlay.style.opacity = '0';
        return;
      }

      const currentAngle =
        Number.parseFloat(overlay.style.getPropertyValue('--glow-angle')) || 0;
      const targetAngle =
        (180 * Math.atan2(pointer.y - centerY, pointer.x - centerX)) / Math.PI + 90;
      const angleDifference = ((targetAngle - currentAngle + 540) % 360) - 180;
      const nextAngle = currentAngle + angleDifference;

      angleAnimation?.stop();
      angleAnimation = animate(currentAngle, nextAngle, {
        duration: 0.2,
        ease: [0.16, 1, 0.3, 1],
        onUpdate: value => overlay.style.setProperty('--glow-angle', `${value}deg`),
      });
      overlay.style.opacity = '1';
    };

    const handlePointerMove = (event: PointerEvent) => {
      pointer = { x: event.clientX, y: event.clientY };
      const nextBox =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>(boxSelector)
          : null;

      if (!nextBox) {
        hide();
        return;
      }

      if (activeBox !== nextBox) {
        angleAnimation?.stop();
        angleAnimation = null;
        activeBox = nextBox;
      }

      update();
    };

    const handlePointerLeave = () => hide();
    const handleScrollOrResize = () => update();

    document.addEventListener('pointermove', handlePointerMove, { passive: true });
    window.addEventListener('pointerleave', handlePointerLeave);
    window.addEventListener('scroll', handleScrollOrResize, { passive: true });
    window.addEventListener('resize', handleScrollOrResize, { passive: true });

    return () => {
      angleAnimation?.stop();
      document.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerleave', handlePointerLeave);
      window.removeEventListener('scroll', handleScrollOrResize);
      window.removeEventListener('resize', handleScrollOrResize);
    };
  }, []);

  return <div ref={overlayRef} className="glowing-effect-overlay" aria-hidden="true" />;
}
