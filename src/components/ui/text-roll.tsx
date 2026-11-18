import {
  motion,
  useReducedMotion,
  type Target,
  type TargetAndTransition,
  type Transition,
  type VariantLabels,
} from 'motion/react';

export type TextRollProps = {
  children: string;
  duration?: number;
  getEnterDelay?: (index: number) => number;
  getExitDelay?: (index: number) => number;
  className?: string;
  transition?: Transition;
  variants?: {
    enter?: {
      initial?: Target | VariantLabels | boolean;
      animate?: TargetAndTransition | VariantLabels;
    };
    exit?: {
      initial?: Target | VariantLabels | boolean;
      animate?: TargetAndTransition | VariantLabels;
    };
  };
  onAnimationComplete?: () => void;
};

export function TextRoll({
  children,
  duration = 0.5,
  getEnterDelay = (index) => index * 0.1,
  getExitDelay = (index) => index * 0.1 + 0.2,
  className = '',
  transition = { ease: 'easeIn' },
  variants,
  onAnimationComplete,
}: TextRollProps) {
  const reduceMotion = useReducedMotion();

  if (reduceMotion) {
    return <span className={`text-roll ${className}`}>{children}</span>;
  }

  const letters = children.split('');

  return (
    <span className={`text-roll ${className}`}>
      {letters.map((letter, index) => {
        const character = letter === ' ' ? '\u00a0' : letter;

        return (
          <span
            className="text-roll-letter"
            key={`${letter}-${index}`}
            aria-hidden="true"
          >
            <motion.span
              className="text-roll-face text-roll-face-enter"
              initial={variants?.enter?.initial ?? { rotateX: 0 }}
              animate={variants?.enter?.animate ?? { rotateX: 90 }}
              transition={{
                ...transition,
                duration,
                delay: getEnterDelay(index),
              }}
            >
              {character}
            </motion.span>
            <motion.span
              className="text-roll-face text-roll-face-exit"
              initial={variants?.exit?.initial ?? { rotateX: 90 }}
              animate={variants?.exit?.animate ?? { rotateX: 0 }}
              transition={{
                ...transition,
                duration,
                delay: getExitDelay(index),
              }}
              onAnimationComplete={
                index === letters.length - 1 ? onAnimationComplete : undefined
              }
            >
              {character}
            </motion.span>
            <span className="text-roll-measure">{character}</span>
          </span>
        );
      })}
      <span className="text-roll-sr-only">{children}</span>
    </span>
  );
}
